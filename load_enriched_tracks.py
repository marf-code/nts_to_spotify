#!/usr/bin/env python3
"""
Load an enriched-tracks CSV into the spotify database (radio.enriched_tracks).

The CSV must be in the shape exported by the playlist enrichment tooling,
i.e. with a header like:

    #,Song,Artist,BPM,Camelot,Energy,Added At,Duration,Popularity,Genres,
    Parent Genres,Album,Album Date,Dance,Acoustic,Instrumental,Valence,
    Speech,Live,Loud (Db),Key,Time Signature,Spotify Track Id,Label,ISRC,Explicit

Usage:
    python load_enriched_tracks.py <input_csv> [--playlist-name NAME] [--show-host HOST] [--append | --replace]

Examples:
    python load_enriched_tracks.py sasha_crush.csv --show-host "Sasha Crush"
    python load_enriched_tracks.py "chico blanco.csv" --playlist-name "chico blanco"

By default the playlist name is derived from the CSV filename. If rows for
that playlist name already exist, the script refuses to load (to avoid
accidental double-loads) unless --append is passed; --replace swaps them out.
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

# CSV header -> radio.enriched_tracks column (same names, in export order)
CSV_COLUMNS = [
    "#", "Song", "Artist", "BPM", "Camelot", "Energy", "Added At",
    "Duration", "Popularity", "Genres", "Parent Genres", "Album",
    "Album Date", "Dance", "Acoustic", "Instrumental", "Valence",
    "Speech", "Live", "Loud (Db)", "Key", "Time Signature",
    "Spotify Track Id", "Label", "ISRC", "Explicit",
]

NUMERIC_COLUMNS = {
    "#", "BPM", "Energy", "Popularity", "Dance", "Acoustic",
    "Instrumental", "Valence", "Speech", "Live", "Loud (Db)",
    "Time Signature",
}


def read_csv(filepath):
    """Read the CSV, validate its shape, and return rows as lists of values."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Some exports have stray whitespace in the header (e.g. " #")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]

        missing = [c for c in CSV_COLUMNS if c not in reader.fieldnames]
        if missing:
            sys.exit(
                f"CSV is not in the expected enriched-tracks shape.\n"
                f"Missing columns: {', '.join(missing)}\n"
                f"Found columns:   {', '.join(reader.fieldnames)}"
            )
        extra = [c for c in reader.fieldnames if c not in CSV_COLUMNS]
        if extra:
            print(f"Ignoring extra columns: {', '.join(extra)}")

        rows = []
        for row in reader:
            values = []
            for col in CSV_COLUMNS:
                value = (row.get(col) or "").strip()
                if value == "" and col in NUMERIC_COLUMNS:
                    value = None
                values.append(value)
            rows.append(values)
        return rows


def main():
    parser = argparse.ArgumentParser(
        description="Load an enriched-tracks CSV into radio.enriched_tracks."
    )
    parser.add_argument("csv_file", help="Path to the enriched CSV")
    parser.add_argument(
        "--playlist-name",
        help='Value for "Playlist Name" (default: CSV filename without extension)',
    )
    parser.add_argument("--show-host", help="Value for show_host (default: empty)")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Load even if rows for this playlist name already exist",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing rows for this playlist name before loading",
    )
    args = parser.parse_args()

    playlist_name = args.playlist_name or os.path.splitext(
        os.path.basename(args.csv_file)
    )[0]

    rows = read_csv(args.csv_file)
    if not rows:
        sys.exit("CSV has no data rows, nothing to load.")

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()

        cur.execute(
            'SELECT count(*) FROM radio.enriched_tracks WHERE "Playlist Name" = %s',
            (playlist_name,),
        )
        existing = cur.fetchone()[0]
        if existing and args.replace:
            cur.execute(
                'DELETE FROM radio.enriched_tracks WHERE "Playlist Name" = %s',
                (playlist_name,),
            )
        elif existing and not args.append:
            sys.exit(
                f'Playlist "{playlist_name}" already has {existing} rows in '
                f"radio.enriched_tracks. Re-run with --append or --replace."
            )

        quoted_cols = ", ".join(f'"{c}"' for c in CSV_COLUMNS)
        execute_values(
            cur,
            f'INSERT INTO radio.enriched_tracks ({quoted_cols}, "Playlist Name", show_host) VALUES %s',
            [values + [playlist_name, args.show_host] for values in rows],
        )
        conn.commit()
    finally:
        conn.close()

    host = args.show_host or "(none)"
    print(
        f'Loaded {len(rows)} tracks into radio.enriched_tracks '
        f'(playlist: "{playlist_name}", show_host: {host}).'
    )


if __name__ == "__main__":
    main()
