#!/usr/bin/env python3
"""
Load an enriched-tracks CSV into the spotify database: one radio.track row per
Spotify track and the playlist's membership in radio.playlist / radio.playlist_track.

The CSV must be in the shape exported by the playlist enrichment tooling,
i.e. with a header like:

    #,Song,Artist,BPM,Camelot,Energy,Added At,Duration,Popularity,Genres,
    Parent Genres,Album,Album Date,Dance,Acoustic,Instrumental,Valence,
    Speech,Live,Loud (Db),Key,Time Signature,Spotify Track Id,Label,ISRC,Explicit

Usage:
    python load_enriched_tracks.py <input_csv> [--playlist-name NAME] [--spotify-playlist-id ID]
        [--show-host HOST] [--append | --replace]

Examples:
    python load_enriched_tracks.py sasha_crush.csv --show-host "Sasha Crush"
    python load_enriched_tracks.py "chico blanco.csv" --playlist-name "chico blanco"

By default the playlist name is derived from the CSV filename. If rows for
that playlist name already exist, the script refuses to load (to avoid
accidental double-loads) unless --append is passed; --replace swaps them out.

Track attributes are upserted: a blank CSV value never overwrites a stored one,
so fields only Chosic exports carry (popularity, genres, label) survive later
syncs. Rows without a Spotify Track Id are skipped.
"""

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}

# Enriched-CSV header, in export order
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


PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PERCENT_FEATURES = {  # CSV 0-100 column -> radio.track 0-1 column
    "Energy": "energy", "Dance": "danceability", "Valence": "valence", "Acoustic": "acousticness",
    "Instrumental": "instrumentalness", "Speech": "speechiness", "Live": "liveness",
}
TRACK_COLUMNS = [
    "spotify_track_id", "name", "artists", "album", "album_release_date", "isrc", "duration_ms",
    "explicit", "popularity", "label", "genres", "parent_genres", "tempo", "key", "mode",
    "time_signature", *PERCENT_FEATURES.values(), "loudness", "features_fetched_at",
]

UPSERT_TRACKS = f"""
INSERT INTO radio.track ({", ".join(TRACK_COLUMNS)}) VALUES %s
ON CONFLICT (spotify_track_id) DO UPDATE SET
    {", ".join(f"{c} = COALESCE(EXCLUDED.{c}, radio.track.{c})" for c in TRACK_COLUMNS[1:-1])},
    features_fetched_at = COALESCE(radio.track.features_fetched_at, EXCLUDED.features_fetched_at),
    updated_at = now()
"""


def split_list(value):
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    return items or None


def key_and_mode(key, camelot):
    """Spotify pitch class and mode from Key text like "C♯/D♭ minor" and Camelot like "12A"."""
    pitch = (key or "").replace("♯", "#").split(" ")[0].split("/")[0]
    pitch_class = PITCH_CLASSES.index(pitch) if pitch in PITCH_CLASSES else None
    # Some exports drop " minor" from Key; the Camelot letter (A = minor) is reliable.
    if camelot and camelot[-1] in "AB":
        mode = 0 if camelot[-1] == "A" else 1
    elif pitch_class is not None:
        mode = 0 if key.endswith(" minor") else 1
    else:
        mode = None
    return pitch_class, mode


def duration_ms(value):
    m = re.fullmatch(r"(\d+):(\d{2})", value or "")
    return (int(m.group(1)) * 60 + int(m.group(2))) * 1000 if m else None


def track_row(values):
    """radio.track values for one CSV row, in TRACK_COLUMNS order."""
    r = dict(zip(CSV_COLUMNS, values))
    key, mode = key_and_mode(r["Key"], r["Camelot"])
    features = [float(r[c]) / 100 if r[c] is not None else None for c in PERCENT_FEATURES]
    has_features = any(f is not None for f in features)
    return (
        r["Spotify Track Id"], r["Song"] or None, r["Artist"] or None, r["Album"] or None,
        r["Album Date"] or None, r["ISRC"] or None, duration_ms(r["Duration"]),
        {"yes": True, "no": False}.get(r["Explicit"]), r["Popularity"], r["Label"] or None,
        split_list(r["Genres"]), split_list(r["Parent Genres"]), r["BPM"], key, mode,
        r["Time Signature"], *features, r["Loud (Db)"], datetime.now(timezone.utc) if has_features else None,
    )


def upsert_tracks(cur, rows):
    """Upsert radio.track from CSV rows; returns the rows that carry a Spotify Track Id."""
    id_index = CSV_COLUMNS.index("Spotify Track Id")
    rows = [v for v in rows if v[id_index]]
    by_id = {v[id_index]: track_row(v) for v in rows}
    if by_id:
        execute_values(cur, UPSERT_TRACKS, list(by_id.values()))
    return rows


def playlist_id(cur, name, spotify_playlist_id, show_host):
    if spotify_playlist_id:
        cur.execute("SELECT playlist_id FROM radio.playlist WHERE spotify_playlist_id = %s",
                    (spotify_playlist_id,))
        found = cur.fetchone()
        if found:
            cur.execute("UPDATE radio.playlist SET name = %s, show_host = COALESCE(%s, show_host), "
                        "loaded_at = now() WHERE playlist_id = %s", (name, show_host, found[0]))
            return found[0]
    cur.execute("SELECT playlist_id, spotify_playlist_id FROM radio.playlist WHERE name = %s", (name,))
    found = cur.fetchone()
    if found and (not spotify_playlist_id or found[1] in (None, spotify_playlist_id)):
        cur.execute("UPDATE radio.playlist SET spotify_playlist_id = COALESCE(%s, spotify_playlist_id), "
                    "show_host = COALESCE(%s, show_host), loaded_at = now() WHERE playlist_id = %s",
                    (spotify_playlist_id, show_host, found[0]))
        return found[0]
    if found:  # A different Spotify playlist already holds this name.
        name = f"{name} ({spotify_playlist_id})"
    cur.execute("INSERT INTO radio.playlist (name, spotify_playlist_id, show_host) VALUES (%s, %s, %s) "
                "RETURNING playlist_id", (name, spotify_playlist_id, show_host))
    return cur.fetchone()[0]


def main():
    parser = argparse.ArgumentParser(
        description="Load an enriched-tracks CSV into radio.track and radio.playlist_track."
    )
    parser.add_argument("csv_file", help="Path to the enriched CSV")
    parser.add_argument(
        "--playlist-name",
        help="Playlist name (default: CSV filename without extension)",
    )
    parser.add_argument("--spotify-playlist-id", help="Spotify ID of the playlist, when it has one")
    parser.add_argument("--show-host", help="NTS host the playlist comes from (default: empty)")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Add after the playlist's existing tracks",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the playlist's existing tracks",
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
        loaded = upsert_tracks(cur, rows)
        if not loaded:
            sys.exit("No rows have a Spotify Track Id, nothing to load.")

        pid = playlist_id(cur, playlist_name, args.spotify_playlist_id, args.show_host)
        cur.execute("SELECT count(*), coalesce(max(position), 0) FROM radio.playlist_track "
                    "WHERE playlist_id = %s", (pid,))
        existing, last_position = cur.fetchone()
        if existing and args.replace:
            cur.execute("DELETE FROM radio.playlist_track WHERE playlist_id = %s", (pid,))
            last_position = 0
        elif existing and not args.append:
            sys.exit(
                f'Playlist "{playlist_name}" already has {existing} tracks in '
                f"radio.playlist_track. Re-run with --append or --replace."
            )

        id_index = CSV_COLUMNS.index("Spotify Track Id")
        added_index = CSV_COLUMNS.index("Added At")
        execute_values(
            cur,
            "INSERT INTO radio.playlist_track (playlist_id, position, spotify_track_id, added_at) VALUES %s",
            [(pid, last_position + i, v[id_index], v[added_index] or None)
             for i, v in enumerate(loaded, 1)],
        )
        conn.commit()
    finally:
        conn.close()

    skipped = len(rows) - len(loaded)
    host = args.show_host or "(none)"
    print(
        f'Loaded {len(loaded)} tracks into radio.playlist_track '
        f'(playlist: "{playlist_name}", show_host: {host})'
        + (f"; skipped {skipped} rows without a Spotify Track Id." if skipped else ".")
    )


if __name__ == "__main__":
    main()
