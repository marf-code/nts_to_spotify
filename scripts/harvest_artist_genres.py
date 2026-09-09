#!/usr/bin/env python3
"""
Fetch Last.fm top tags for every artist in radio.nts_tracks and store them in
radio.artist_genres. Tags are kept raw (as JSON) and also reduced to the genre
labels NTS itself uses on episodes, so artist genres and episode genres share
one vocabulary.

Artists are processed most-played first and the table is the progress record,
so a stopped run resumes. Requires LASTFM_API_KEY in .env or the environment.

Usage:
    python scripts/harvest_artist_genres.py [--min-plays N] [--limit N] [--workers N]
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}
API = "https://ws.audioscrobbler.com/2.0/"
BATCH = 200
MIN_TAG_WEIGHT = 10
ALIASES = {
    "electronic": "electronica", "idm": "electronica", "hip-hop": "hip hop", "rap": "hip hop",
    "post-punk": "post punk", "drum and bass": "drum & bass", "dnb": "drum & bass",
    "r&b": "rnb", "synthpop": "synth pop", "trip-hop": "trip hop",
}
SKIP_ARTISTS = {"unknown artist", "unknown", "various artists", "various", "?", "n/a", ""}

DDL = """
CREATE TABLE IF NOT EXISTS radio.artist_genres (
    artist_key   text PRIMARY KEY,
    artist       text NOT NULL,
    lastfm_name  text,
    lastfm_tags  jsonb,
    genres       text[],
    found        boolean NOT NULL,
    fetched_at   timestamptz NOT NULL DEFAULT now()
);
"""


class RateLimiter:
    def __init__(self, per_second):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if now < self.next_at:
                time.sleep(self.next_at - now)
                now = time.monotonic()
            self.next_at = now + self.interval


def load_vocab(cur):
    cur.execute("SELECT DISTINCT lower(genre) FROM radio.nts_episode_genres")
    return {r[0] for r in cur.fetchall()}


def pending_artists(cur, min_plays, limit):
    cur.execute(
        """
        WITH a AS (
            SELECT min(artist) AS name, lower(artist) AS key, count(*) AS plays
            FROM radio.nts_tracks
            WHERE nullif(trim(artist), '') IS NOT NULL
            GROUP BY lower(artist)
        )
        SELECT name, key, plays FROM a
        WHERE plays >= %s
          AND NOT EXISTS (SELECT 1 FROM radio.artist_genres g WHERE g.artist_key = a.key)
        ORDER BY plays DESC, key
        """ + (" LIMIT %s" if limit else ""),
        (min_plays, limit) if limit else (min_plays,),
    )
    return [(name, key) for name, key, _ in cur.fetchall() if key not in SKIP_ARTISTS]


def fetch_tags(session, limiter, api_key, artist):
    params = {"method": "artist.gettoptags", "artist": artist, "autocorrect": 1,
              "api_key": api_key, "format": "json"}
    for attempt in range(4):
        limiter.wait()
        try:
            resp = session.get(API, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 200:
            data = resp.json()
            if "error" in data:
                return None
            tags = data.get("toptags", {})
            return tags.get("@attr", {}).get("artist"), [
                {"name": t["name"], "count": int(t.get("count") or 0)} for t in tags.get("tag", [])
            ]
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        return None
    raise RuntimeError(f"gave up on {artist}")


def reduce_genres(tags, vocab):
    out = []
    for t in tags:
        if t["count"] < MIN_TAG_WEIGHT:
            continue
        name = t["name"].strip().lower()
        name = ALIASES.get(name, name)
        if name in vocab and name not in out:
            out.append(name)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-plays", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rate", type=float, default=4.0, help="requests per second across all workers")
    args = parser.parse_args()

    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        sys.exit("LASTFM_API_KEY is not set")

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    vocab = load_vocab(cur)
    artists = pending_artists(cur, args.min_plays, args.limit)
    print(f"{len(artists)} artists to fetch ({len(vocab)} genre labels in vocabulary)", file=sys.stderr)
    if not artists:
        return

    session = requests.Session()
    session.headers["User-Agent"] = "nts_to_spotify/1.0"
    limiter = RateLimiter(args.rate)

    def job(item):
        name, key = item
        return name, key, fetch_tags(session, limiter, api_key, name)

    done = found = failed = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(artists), BATCH):
            rows = []
            for fut in as_completed([pool.submit(job, a) for a in artists[start:start + BATCH]]):
                try:
                    name, key, result = fut.result()
                except RuntimeError as exc:
                    failed += 1
                    print(exc, file=sys.stderr)
                    continue
                if result is None:
                    rows.append((key, name, None, None, None, False))
                else:
                    lastfm_name, tags = result
                    found += 1
                    rows.append((key, name, lastfm_name, Json(tags), reduce_genres(tags, vocab), True))
                done += 1
            execute_values(
                cur,
                "INSERT INTO radio.artist_genres (artist_key, artist, lastfm_name, lastfm_tags, genres, found) "
                "VALUES %s ON CONFLICT (artist_key) DO UPDATE SET lastfm_name = EXCLUDED.lastfm_name, "
                "lastfm_tags = EXCLUDED.lastfm_tags, genres = EXCLUDED.genres, found = EXCLUDED.found, "
                "fetched_at = now()",
                rows,
            )
            rate = done / max(time.time() - started, 1)
            print(f"{done}/{len(artists)} artists, {found} found, {failed} failed, {rate:.1f}/s", file=sys.stderr)
    print(f"finished: {done} artists, {found} with Last.fm data, {failed} failed", file=sys.stderr)


if __name__ == "__main__":
    main()
