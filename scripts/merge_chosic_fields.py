#!/usr/bin/env python3
"""
Store Popularity, Genres, Parent Genres, Label and Time Signature from Chosic
exports on radio.track, matched by Spotify Track Id.

Spotify withholds those fields from apps created after its 2026 API changes,
so synced playlists arrive without them; Chosic exports still carry them.
radio.track never overwrites a stored value with a blank one, so fields stored
here survive later syncs, and a track exported once is filled in every
playlist it appears in. No playlist membership is recorded; use
load_enriched_tracks.py for that.

Usage:
    python scripts/merge_chosic_fields.py [chosic_export.csv ...]
"""

import argparse
import os
import sys

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from load_enriched_tracks import DB_CONFIG, read_csv, upsert_tracks  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("csv_files", nargs="*", help="Chosic playlist exports")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        for path in args.csv_files:
            rows = upsert_tracks(cur, read_csv(path))
            print(f"{path}: {len(rows)} tracks stored")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
