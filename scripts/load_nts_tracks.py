#!/usr/bin/env python3
"""
Load the tracklist CSV written by harvest_tracklists.py into radio.nts_tracks.

Rows are keyed on (show_alias, episode_alias, position) so re-running upserts
onto existing rows; pass --truncate to replace the table contents instead.

Usage:
    python scripts/load_nts_tracks.py [tracks.csv] [--truncate]
"""

import argparse
import csv
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}

COLUMNS = ["show_alias", "episode_alias", "position", "track", "artist",
           "offset_seconds", "duration_seconds", "isrc", "musicbrainz_track_id"]
INT_COLUMNS = {"position", "offset_seconds", "duration_seconds"}

DDL = """
CREATE TABLE IF NOT EXISTS radio.nts_tracks (
    id                   serial PRIMARY KEY,
    show_alias           text NOT NULL,
    episode_alias        text NOT NULL,
    position             integer NOT NULL,
    track                text,
    artist               text,
    offset_seconds       integer,
    duration_seconds     integer,
    isrc                 text,
    musicbrainz_track_id text,
    UNIQUE (show_alias, episode_alias, position)
);
CREATE INDEX IF NOT EXISTS nts_tracks_show_alias_idx ON radio.nts_tracks (show_alias);
CREATE INDEX IF NOT EXISTS nts_tracks_artist_idx     ON radio.nts_tracks (artist);
CREATE INDEX IF NOT EXISTS nts_tracks_track_idx      ON radio.nts_tracks (track);
"""


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"CSV is missing columns: {', '.join(missing)}")
        rows = []
        for row in reader:
            values = []
            for c in COLUMNS:
                v = (row.get(c) or "").strip()
                if c in INT_COLUMNS:
                    values.append(int(float(v)) if v else None)
                else:
                    values.append(v or None)
            rows.append(values)
        return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tracks_csv", nargs="?", default=".scratch/nts_tracklists.csv")
    parser.add_argument("--truncate", action="store_true",
                        help="Empty the table first instead of upserting onto existing rows")
    args = parser.parse_args()

    rows = read_rows(args.tracks_csv)
    if not rows:
        sys.exit("CSV has no data rows, nothing to load.")

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(DDL)
        if args.truncate:
            cur.execute("TRUNCATE radio.nts_tracks RESTART IDENTITY")
        cols = ", ".join(COLUMNS)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS
                            if c not in ("show_alias", "episode_alias", "position"))
        execute_values(
            cur,
            f"INSERT INTO radio.nts_tracks ({cols}) VALUES %s "
            f"ON CONFLICT (show_alias, episode_alias, position) DO UPDATE SET {updates}",
            rows,
            page_size=5000,
        )
        conn.commit()
        cur.execute("SELECT count(*) FROM radio.nts_tracks")
        print(f"loaded {len(rows)} rows; radio.nts_tracks now has {cur.fetchone()[0]} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
