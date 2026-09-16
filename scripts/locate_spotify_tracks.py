#!/usr/bin/env python3
"""
Look up every distinct (track, artist) in radio.nts_tracks on Spotify and store
the result in radio.spotify_tracks.

Tracks that came with an ISRC are matched exactly via Spotify's isrc: search;
the rest go through the same fielded-then-loose search and similarity scoring
the playlist builder uses. Placeholder titles or artists ("Untitled", "??",
"Unknown Artist") are never text-searched. Anything below ACCEPT_SCORE is
stored as not found so it is not retried.

Pairs that appear in the most episode tracklists go first; the table is the progress record, so
a stopped run resumes. Join back with:

    SELECT t.*, s.spotify_track_id
    FROM radio.nts_tracks t
    JOIN radio.spotify_tracks s
      ON s.track_key = lower(trim(t.track)) || E'\\t' || lower(trim(t.artist))

Requires SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in .env or the environment.

Usage:
    python scripts/locate_spotify_tracks.py [--min-appearances N] [--limit N] [--workers N] [--rate R]
"""

import argparse
import base64
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_values

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "spotify_scripts"))
from match_utils import ACCEPT_SCORE, similarity  # noqa: E402
from spotify_v2 import _normalize_for_search  # noqa: E402

load_dotenv(os.path.join(HERE, "..", ".env"))

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}
TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
BATCH = 200
MAX_RETRY_AFTER = 600
PLACEHOLDER = re.compile(
    r"^\W*(unknown( track| artist)?|untitled|unreleased|unknown|various( artists)?|id|n/?a|tba|\?+)\W*$", re.I
)

DDL = """
CREATE TABLE IF NOT EXISTS radio.spotify_tracks (
    track_key           text PRIMARY KEY,
    track               text NOT NULL,
    artist              text NOT NULL,
    nts_isrc            text,
    spotify_track_id    text,
    spotify_track_name  text,
    spotify_artists     text,
    spotify_album       text,
    spotify_isrc        text,
    spotify_popularity  integer,
    spotify_duration_ms integer,
    match_method        text NOT NULL,
    match_score         numeric,
    found               boolean NOT NULL,
    fetched_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS spotify_tracks_track_id_idx ON radio.spotify_tracks (spotify_track_id);
"""

UPSERT = """
INSERT INTO radio.spotify_tracks (
    track_key, track, artist, nts_isrc, spotify_track_id, spotify_track_name, spotify_artists,
    spotify_album, spotify_isrc, spotify_popularity, spotify_duration_ms, match_method,
    match_score, found
) VALUES %s
ON CONFLICT (track_key) DO UPDATE SET
    nts_isrc = EXCLUDED.nts_isrc,
    spotify_track_id = EXCLUDED.spotify_track_id,
    spotify_track_name = EXCLUDED.spotify_track_name,
    spotify_artists = EXCLUDED.spotify_artists,
    spotify_album = EXCLUDED.spotify_album,
    spotify_isrc = EXCLUDED.spotify_isrc,
    spotify_popularity = EXCLUDED.spotify_popularity,
    spotify_duration_ms = EXCLUDED.spotify_duration_ms,
    match_method = EXCLUDED.match_method,
    match_score = EXCLUDED.match_score,
    found = EXCLUDED.found,
    fetched_at = now()
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

    def pause(self, seconds):
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)


class ClientCredentials:
    """Shared client-credentials bearer token, refreshed shortly before expiry."""

    def __init__(self, session, client_id, client_secret):
        self.session = session
        self.auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self.lock = threading.Lock()
        self.token = None
        self.expires_at = 0.0

    def get(self, force=False):
        with self.lock:
            if force or not self.token or time.time() >= self.expires_at:
                resp = self.session.post(TOKEN_URL, headers={"Authorization": f"Basic {self.auth}"},
                                         data={"grant_type": "client_credentials"}, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                self.token = data["access_token"]
                self.expires_at = time.time() + data["expires_in"] - 300
            return self.token


class Spotify:
    def __init__(self, session, creds, limiter):
        self.session = session
        self.creds = creds
        self.limiter = limiter

    def search(self, query, limit):
        attempt = 0
        while attempt < 6:
            token = self.creds.get()
            self.limiter.wait()
            try:
                resp = self.session.get(
                    SEARCH_URL, params={"q": query, "type": "track", "limit": limit},
                    headers={"Authorization": f"Bearer {token}"}, timeout=30,
                )
            except requests.RequestException:
                attempt += 1
                time.sleep(min(2 ** attempt, 30))
                continue
            if resp.status_code == 200:
                return resp.json().get("tracks", {}).get("items", [])
            if resp.status_code == 401:
                self.creds.get(force=True)
                attempt += 1
                continue
            if resp.status_code == 429:
                wait = min(int(resp.headers.get("Retry-After", "1")) + 1, MAX_RETRY_AFTER)
                print(f"rate limited, pausing all workers {wait}s", file=sys.stderr)
                self.limiter.pause(wait)
                continue
            if resp.status_code >= 500:
                attempt += 1
                time.sleep(min(2 ** attempt, 30))
                continue
            raise RuntimeError(f"search {query!r} failed with HTTP {resp.status_code}")
        raise RuntimeError(f"gave up on search {query!r}")


def pending_pairs(cur, min_appearances, limit):
    cur.execute(
        """
        WITH p AS (
            SELECT lower(trim(track)) || E'\\t' || lower(trim(artist)) AS key,
                   min(trim(track)) AS track, min(trim(artist)) AS artist,
                   mode() WITHIN GROUP (ORDER BY isrc) AS isrc,
                   count(*) AS appearances
            FROM radio.nts_tracks
            WHERE nullif(trim(track), '') IS NOT NULL AND nullif(trim(artist), '') IS NOT NULL
            GROUP BY lower(trim(track)), lower(trim(artist))
        )
        SELECT key, track, artist, isrc, appearances FROM p
        WHERE appearances >= %s
          AND NOT EXISTS (SELECT 1 FROM radio.spotify_tracks s WHERE s.track_key = p.key)
        ORDER BY appearances DESC, key
        """ + (" LIMIT %s" if limit else ""),
        (min_appearances, limit) if limit else (min_appearances,),
    )
    return [(key, track, artist, isrc) for key, track, artist, isrc, _ in cur.fetchall()]


def score(track, artist, item):
    got_artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
    return 0.6 * similarity(track, item.get("name", "")) + 0.4 * similarity(artist, got_artists)


def locate(spotify, track, artist, isrc):
    """Return (item, method, score) for the best Spotify match, or (None, method, score)."""
    isrc = re.sub(r"[^A-Za-z0-9]", "", isrc or "").upper()
    if len(isrc) == 12:
        items = spotify.search(f"isrc:{isrc}", 1)
        if items:
            return items[0], "isrc", 1.0
    if PLACEHOLDER.match(track) or PLACEHOLDER.match(artist):
        return None, "placeholder", None
    clean_track, clean_artist = _normalize_for_search(track), _normalize_for_search(artist)
    items = spotify.search(f'track:"{clean_track}" artist:"{clean_artist}"', 5)
    if not items:
        items = spotify.search(f"{clean_track} {clean_artist}", 5)
    if not items:
        return None, "search", None
    best = max(items, key=lambda item: score(track, artist, item))
    best_score = score(track, artist, best)
    if best_score < ACCEPT_SCORE:
        return None, "search", best_score
    return best, "search", best_score


def row_for(key, track, artist, isrc, item, method, match_score):
    if item is None:
        return (key, track, artist, isrc, None, None, None, None, None, None, None,
                method, match_score, False)
    return (
        key, track, artist, isrc, item["id"], item.get("name"),
        ", ".join(a.get("name", "") for a in item.get("artists", [])),
        item.get("album", {}).get("name"), item.get("external_ids", {}).get("isrc"),
        item.get("popularity"), item.get("duration_ms"), method, match_score, True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-appearances", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rate", type=float, default=3.0, help="requests per second across all workers")
    args = parser.parse_args()

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set")

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    pairs = pending_pairs(cur, args.min_appearances, args.limit)
    print(f"{len(pairs)} track/artist pairs to look up", file=sys.stderr)
    if not pairs:
        return

    session = requests.Session()
    session.headers["User-Agent"] = "nts_to_spotify/1.0"
    creds = ClientCredentials(session, client_id, client_secret)
    creds.get()
    spotify = Spotify(session, creds, RateLimiter(args.rate))

    def job(pair):
        key, track, artist, isrc = pair
        item, method, match_score = locate(spotify, track, artist, isrc)
        return row_for(key, track, artist, isrc, item, method, match_score)

    done = found = failed = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(pairs), BATCH):
            rows = []
            try:
                for fut in as_completed([pool.submit(job, p) for p in pairs[start:start + BATCH]]):
                    try:
                        row = fut.result()
                    except Exception as exc:
                        failed += 1
                        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
                        continue
                    rows.append(row)
                    done += 1
                    found += row[-1]
            finally:
                if rows:
                    execute_values(cur, UPSERT, rows)
            rate = done / max(time.time() - started, 1)
            print(f"{done}/{len(pairs)} pairs, {found} found, {failed} failed, {rate:.1f}/s", file=sys.stderr)
    print(f"finished: {done} pairs, {found} found on Spotify, {failed} failed", file=sys.stderr)


if __name__ == "__main__":
    main()
