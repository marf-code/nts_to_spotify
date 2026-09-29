#!/usr/bin/env python3
"""
Fill Popularity, Genres, Parent Genres, Label and Time Signature on
radio.enriched_tracks from Chosic exports, matched by Spotify Track Id.

Spotify withholds those fields from apps created after its 2026 API changes,
so synced playlists arrive without them; Chosic exports still carry them.
Chosic values are kept in radio.chosic_track_fields so they survive
sync_my_playlists.py replacing a playlist's rows, and a track exported once
is filled in every playlist it appears in.

Each run:
  1. stores fields from any Chosic CSVs given, plus from enriched_tracks rows
     that already have them (earlier Chosic loads), in chosic_track_fields;
  2. fills blanks in enriched_tracks from chosic_track_fields.

Usage:
    python scripts/merge_chosic_fields.py [chosic_export.csv ...]
"""

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from load_enriched_tracks import CSV_COLUMNS, DB_CONFIG, read_csv  # noqa: E402

FIELDS = {  # enriched_tracks column -> chosic_track_fields column
    "Popularity": "popularity",
    "Genres": "genres",
    "Parent Genres": "parent_genres",
    "Label": "label",
    "Time Signature": "time_signature",
}
TEXT_FIELDS = {"Genres", "Parent Genres", "Label"}

DDL = """
CREATE TABLE IF NOT EXISTS radio.chosic_track_fields (
    spotify_track_id  text PRIMARY KEY,
    popularity        integer,
    genres            text,
    parent_genres     text,
    label             text,
    time_signature    integer,
    loaded_at         timestamptz NOT NULL DEFAULT now()
)
"""

UPSERT = f"""
INSERT INTO radio.chosic_track_fields (spotify_track_id, {", ".join(FIELDS.values())})
VALUES %s
ON CONFLICT (spotify_track_id) DO UPDATE SET
    {", ".join(f"{c} = COALESCE(EXCLUDED.{c}, radio.chosic_track_fields.{c})" for c in FIELDS.values())},
    loaded_at = now()
"""

# Only rows with Popularity count as Chosic-sourced: synced rows never have it.
CAPTURE_FROM_DB = f"""
INSERT INTO radio.chosic_track_fields (spotify_track_id, {", ".join(FIELDS.values())})
SELECT DISTINCT ON ("Spotify Track Id") "Spotify Track Id", {", ".join(f'"{c}"' for c in FIELDS)}
FROM radio.enriched_tracks
WHERE "Popularity" IS NOT NULL AND "Spotify Track Id" <> ''
ORDER BY "Spotify Track Id", id DESC
ON CONFLICT (spotify_track_id) DO NOTHING
"""


def blank(col):
    return f"NULLIF(t.\"{col}\", '')" if col in TEXT_FIELDS else f't."{col}"'


APPLY = f"""
UPDATE radio.enriched_tracks t SET
    {", ".join(f'"{c}" = COALESCE({blank(c)}, f.{fc})' for c, fc in FIELDS.items())}
FROM radio.chosic_track_fields f
WHERE t."Spotify Track Id" = f.spotify_track_id
  AND ({" OR ".join(f"({blank(c)} IS NULL AND f.{fc} IS NOT NULL)" for c, fc in FIELDS.items())})
"""


def csv_rows(path):
    idx = {c: CSV_COLUMNS.index(c) for c in ["Spotify Track Id", *FIELDS]}
    rows = {}
    for values in read_csv(path):
        track_id = values[idx["Spotify Track Id"]]
        if track_id:
            rows[track_id] = [track_id] + [values[idx[c]] or None for c in FIELDS]
    return list(rows.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("csv_files", nargs="*", help="Chosic playlist exports")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(DDL)
        for path in args.csv_files:
            rows = csv_rows(path)
            if rows:
                execute_values(cur, UPSERT, rows)
            print(f"{path}: {len(rows)} tracks stored")
        cur.execute(CAPTURE_FROM_DB)
        print(f"captured {cur.rowcount} tracks from earlier Chosic loads")
        cur.execute(APPLY)
        print(f"filled {cur.rowcount} rows in radio.enriched_tracks")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
