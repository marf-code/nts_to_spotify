#!/usr/bin/env python3
"""
Load a directory of Chosic playlist-analyzer exports into radio.track,
radio.playlist and radio.playlist_track.

Each CSV is matched to one of your Spotify playlists by name (Chrome replaces
characters like "/" with "_" in download names, so the match ignores those),
and loaded under the playlist's real name and Spotify ID. Chosic stops at 1000
tracks, so for longer playlists the tracks are upserted but an existing,
longer membership list is kept rather than replaced with the truncated one.

Playlists are listed through the Spotify sync app (same .env credentials as
sync_my_playlists.py).

Usage:
    python scripts/load_chosic_exports.py [DIR] [--dry-run]
"""

import argparse
import os
import re
import sys

import psycopg2
from psycopg2.extras import execute_values

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
from load_enriched_tracks import CSV_COLUMNS, DB_CONFIG, playlist_id, read_csv, upsert_tracks  # noqa: E402
from sync_my_playlists import UserToken, my_playlists  # noqa: E402

CHOSIC_TRACK_LIMIT = 1000


def norm(name):
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|~]', "_", name)).strip().lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("dir", nargs="?", default=os.path.join(ROOT, "spotify_playlists_chosic_data"))
    parser.add_argument("--dry-run", action="store_true", help="Show the file-to-playlist matches and exit")
    args = parser.parse_args()

    token = UserToken(os.getenv("SPOTIFY_SYNC_CLIENT_ID"), os.getenv("SPOTIFY_SYNC_CLIENT_SECRET"))
    by_name = {}
    for p in my_playlists(token.get(), include_followed=False):
        by_name.setdefault(norm(p["name"]), []).append(p)

    jobs, unmatched = [], []
    for fname in sorted(os.listdir(args.dir)):
        if not fname.endswith(".csv"):
            continue
        matches = by_name.get(norm(fname[:-4]), [])
        if matches:
            # Same-named playlists export to one file; load it under the first.
            jobs.append((os.path.join(args.dir, fname), matches[0]))
        else:
            unmatched.append(fname)
    print(f"{len(jobs)} files matched to playlists, {len(unmatched)} unmatched")
    for fname in unmatched:
        print(f"  unmatched: {fname}")
    if args.dry_run:
        return

    id_index = CSV_COLUMNS.index("Spotify Track Id")
    added_index = CSV_COLUMNS.index("Added At")
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        for path, p in jobs:
            rows = read_csv(path)
            loaded = upsert_tracks(cur, rows) if rows else []
            if not loaded:
                print(f"skip (no tracks): {p['name']}")
                continue
            pid = playlist_id(cur, p["name"], p["id"], None)
            cur.execute("SELECT count(*) FROM radio.playlist_track WHERE playlist_id = %s", (pid,))
            existing = cur.fetchone()[0]
            capped = p["items"]["total"] > CHOSIC_TRACK_LIMIT
            if capped and existing >= len(loaded):
                print(f"tracks only (Chosic capped at {len(loaded)}, keeping {existing} members): {p['name']}")
            else:
                cur.execute("DELETE FROM radio.playlist_track WHERE playlist_id = %s", (pid,))
                execute_values(
                    cur,
                    "INSERT INTO radio.playlist_track (playlist_id, position, spotify_track_id, added_at) VALUES %s",
                    [(pid, i, v[id_index], v[added_index] or None) for i, v in enumerate(loaded, 1)],
                )
                print(f"loaded {len(loaded)}: {p['name']}")
            conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
