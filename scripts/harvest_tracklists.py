#!/usr/bin/env python3
"""
Fetch the tracklist for every NTS episode and write one CSV of show, track, artist,
plus the episode link and per-track ids so the rows can be loaded into radio.nts_tracks.

Episodes come from radio.nts_episodes (spotify_account_data) by default, or from
a CSV in the shape written by harvest_episodes.py via --episodes-csv.

Uses /api/v2/shows/<show>/episodes/<episode>/tracklist, which returns the whole
list in one response. Output is appended as episodes complete and progress is
recorded in <out>.done, so a stopped run resumes where it left off. Episodes
that fail after retries are listed in <out>.failed and retried on the next run.

Usage:
    python scripts/harvest_tracklists.py [-o out.csv] [--workers N] [--limit N] [--fresh]
"""

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, unquote

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
FIELDS = ["show", "track", "artist", "show_alias", "episode_alias", "position",
          "offset_seconds", "duration_seconds", "isrc", "musicbrainz_track_id"]
BATCH = 2000
RETRIES = 4

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=64))
    return session


def load_episodes_db():
    import psycopg2
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT e.show_alias, e.episode_alias, COALESCE(s.name, e.show_alias) "
            "FROM radio.nts_episodes e LEFT JOIN radio.nts_shows s USING (show_alias) "
            "ORDER BY e.broadcast DESC NULLS LAST")
        return [(s, e, n or s) for s, e, n in cur.fetchall()]
    finally:
        conn.close()


def load_episodes_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [(unquote(r["show_alias"]), unquote(r["episode_alias"]), r.get("show_name") or r["show_alias"])
                for r in csv.DictReader(fh)]


def read_lines(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {line.rstrip("\n") for line in fh if line.strip()}


def fetch_tracklist(session, show, episode):
    url = f"https://www.nts.live/api/v2/shows/{quote(show)}/episodes/{quote(episode)}/tracklist"
    delay = 2
    for attempt in range(RETRIES):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("results") or []
            if resp.status_code == 404:
                return []
            if resp.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {resp.status_code}")
        except (requests.RequestException, ValueError) as exc:
            if attempt == RETRIES - 1:
                raise RuntimeError(str(exc))
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("retries exhausted")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", default=".scratch/nts_tracklists.csv")
    parser.add_argument("--episodes-csv", help="read episodes from this CSV instead of the database")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int, help="only process the first N pending episodes")
    parser.add_argument("--fresh", action="store_true", help="discard existing output and progress")
    args = parser.parse_args()

    done_path, failed_path = args.out + ".done", args.out + ".failed"
    if args.fresh:
        for p in (args.out, done_path, failed_path):
            if os.path.exists(p):
                os.remove(p)

    episodes = load_episodes_csv(args.episodes_csv) if args.episodes_csv else load_episodes_db()
    done = read_lines(done_path)
    pending = [e for e in episodes if f"{e[0]}/{e[1]}" not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f"{len(episodes)} episodes, {len(done)} already done, {len(pending)} to fetch", file=sys.stderr)
    if not pending:
        return

    session = make_session()
    write_header = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    out_fh = open(args.out, "a", newline="", encoding="utf-8")
    done_fh = open(done_path, "a", encoding="utf-8")
    failed_fh = open(failed_path, "w", encoding="utf-8")
    writer = csv.DictWriter(out_fh, fieldnames=FIELDS)
    if write_header:
        writer.writeheader()

    def job(ep):
        show, alias, name = ep
        return ep, fetch_tracklist(session, show, alias)

    processed = tracks_written = failed = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(pending), BATCH):
            futures = [pool.submit(job, ep) for ep in pending[start:start + BATCH]]
            for fut in as_completed(futures):
                try:
                    (show, alias, name), results = fut.result()
                except RuntimeError as exc:
                    failed += 1
                    failed_fh.write(f"{exc}\n")
                    continue
                for position, t in enumerate(results, start=1):
                    title = (t.get("title") or "").strip()
                    artist = (t.get("artist") or "").strip()
                    if not (title or artist):
                        continue
                    writer.writerow({
                        "show": name, "track": title, "artist": artist,
                        "show_alias": show, "episode_alias": alias, "position": position,
                        "offset_seconds": t.get("offset") if t.get("offset") is not None else t.get("offset_estimate"),
                        "duration_seconds": t.get("duration") if t.get("duration") is not None else t.get("duration_estimate"),
                        "isrc": t.get("isrc_id") or "",
                        "musicbrainz_track_id": t.get("musicbrainz_track_id") or "",
                    })
                    tracks_written += 1
                done_fh.write(f"{show}/{alias}\n")
                processed += 1
            out_fh.flush()
            done_fh.flush()
            failed_fh.flush()
            rate = processed / max(time.time() - started, 1)
            print(f"{processed}/{len(pending)} episodes, {tracks_written} tracks, {failed} failed, "
                  f"{rate:.1f} ep/s", file=sys.stderr)

    out_fh.close()
    done_fh.close()
    failed_fh.close()
    print(f"wrote {tracks_written} tracks to {args.out}; {failed} episodes failed (see {failed_path})", file=sys.stderr)


if __name__ == "__main__":
    main()
