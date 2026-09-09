#!/usr/bin/env python3
"""
Load the harvested NTS CSVs into the spotify database (radio.nts_episodes and radio.nts_shows).

Input is the output of harvest_episodes.py:

    show_alias,episode_alias,show_name,location,broadcast,genres,url

url is the natural key; radio.nts_tracks joins on (show_alias, episode_alias). Re-running
upserts rather than duplicating. The shows CSV produced by list_all_shows.py,
when available, is loaded into radio.nts_shows (keyed on the show slug, which
matches nts_episodes.show_alias) and its parsed host is denormalised onto each
episode's show_artist.

Usage:
    python scripts/load_nts_episodes.py [episodes_csv] [--shows CSV] [--truncate]
"""

import argparse
import csv
import os
import sys
from urllib.parse import unquote

import psycopg2
from psycopg2.extras import execute_values

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}

CSV_COLUMNS = ["show_alias", "episode_alias", "show_name", "location", "broadcast", "genres", "url"]
TABLE_COLUMNS = ["show_alias", "episode_alias", "episode_name", "location", "broadcast", "genres", "show_artist", "url"]
SHOW_CSV_COLUMNS = ["name", "artist", "location", "all_locations", "episodes", "url"]
SHOW_TABLE_COLUMNS = ["show_alias", "name", "artist", "location", "all_locations", "episodes", "url"]

DDL = """
CREATE TABLE IF NOT EXISTS radio.nts_episodes (
    id            serial PRIMARY KEY,
    show_alias    text NOT NULL,
    episode_alias text NOT NULL,
    episode_name  text,
    location      text,
    broadcast     timestamptz,
    genres        text,
    show_artist   text,
    url           text NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS nts_episodes_show_alias_idx ON radio.nts_episodes (show_alias);
CREATE INDEX IF NOT EXISTS nts_episodes_location_idx   ON radio.nts_episodes (location);
CREATE INDEX IF NOT EXISTS nts_episodes_broadcast_idx  ON radio.nts_episodes (broadcast);
CREATE TABLE IF NOT EXISTS radio.nts_shows (
    show_alias    text PRIMARY KEY,
    name          text,
    artist        text,
    location      text,
    all_locations text,
    episodes      integer,
    url           text NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS nts_shows_location_idx ON radio.nts_shows (location);
"""


def read_shows(path):
    """Rows for radio.nts_shows, keyed on the slug that nts_episodes.show_alias uses."""
    try:
        fh = open(path, newline="", encoding="utf-8-sig")
    except OSError:
        return []
    with fh:
        rows = []
        for row in csv.DictReader(fh):
            url = row["url"].strip()
            values = [unquote(url.rsplit("/", 1)[-1])]
            for c in SHOW_CSV_COLUMNS[:-1]:
                v = (row.get(c) or "").strip()
                values.append(int(v) if c == "episodes" and v else (v or None))
            values.append(url)
            rows.append(values)
        return rows


def read_episodes(path, artists):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"CSV is missing columns: {', '.join(missing)}")

        rows = []
        for row in reader:
            values = [(row.get(c) or "").strip() or None for c in CSV_COLUMNS[:-1]]
            values.append(artists.get(row["show_alias"]))
            values.append(row["url"].strip())
            rows.append(values)
        return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes_csv", nargs="?", default=".scratch/nts_episodes_full.csv")
    parser.add_argument("--shows", default=".scratch/nts_shows.csv")
    parser.add_argument("--truncate", action="store_true",
                        help="Empty the table first instead of upserting onto existing rows")
    args = parser.parse_args()

    shows = read_shows(args.shows)
    artists = {r[0]: r[2] for r in shows}
    rows = read_episodes(args.episodes_csv, artists)
    if not rows:
        sys.exit("CSV has no data rows, nothing to load.")

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(DDL)
        if args.truncate:
            cur.execute("TRUNCATE radio.nts_episodes RESTART IDENTITY")
            cur.execute("TRUNCATE radio.nts_shows")

        if shows:
            show_cols = ", ".join(SHOW_TABLE_COLUMNS)
            show_updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in SHOW_TABLE_COLUMNS if c != "show_alias")
            execute_values(
                cur,
                f"INSERT INTO radio.nts_shows ({show_cols}) VALUES %s "
                f"ON CONFLICT (show_alias) DO UPDATE SET {show_updates}",
                shows,
                page_size=1000,
            )

        cols = ", ".join(TABLE_COLUMNS)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in TABLE_COLUMNS if c != "url")
        execute_values(
            cur,
            f"INSERT INTO radio.nts_episodes ({cols}) VALUES %s "
            f"ON CONFLICT (url) DO UPDATE SET {updates}",
            rows,
            page_size=1000,
        )
        conn.commit()

        cur.execute("SELECT count(*) FROM radio.nts_episodes")
        total = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM radio.nts_shows")
        show_total = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"Loaded {len(shows)} shows into radio.nts_shows ({show_total} rows total).")
    print(f"Loaded {len(rows)} episodes into radio.nts_episodes ({total} rows total).")


if __name__ == "__main__":
    main()
