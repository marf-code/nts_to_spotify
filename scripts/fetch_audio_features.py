#!/usr/bin/env python3
"""
Fetch audio features (valence, energy, danceability, ...) for every Spotify
track matched in radio.spotify_tracks and store them in
radio.spotify_audio_features.

Spotify's own audio-features endpoint is closed to new apps, so the numbers
come from ReccoBeats, which serves the same schema keyed by Spotify track ID.
Tracks ReccoBeats doesn't know are stored with found = false so they are not
retried. The table is the progress record, so a stopped run resumes, and
re-running picks up tracks matched since the last run. Join back with:

    SELECT s.*, f.valence, f.energy, f.tempo
    FROM radio.spotify_tracks s
    JOIN radio.spotify_audio_features f USING (spotify_track_id)

Usage:
    python scripts/fetch_audio_features.py [--limit N]
"""

import argparse
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "spotify_scripts"))
from playlist_to_enriched_csv import RECCOBEATS_BATCH, fetch_audio_features  # noqa: E402

DB_CONFIG = {
    "host": os.environ.get("SPOTIFY_DB_HOST", "localhost"),
    "port": int(os.environ.get("SPOTIFY_DB_PORT", 5433)),
    "user": os.environ.get("SPOTIFY_DB_USER", "spotify_user"),
    "password": os.environ.get("SPOTIFY_DB_PASSWORD", "spotify_password"),
    "dbname": os.environ.get("SPOTIFY_DB_NAME", "spotify_account_data"),
}
CHUNK = RECCOBEATS_BATCH * 10
FEATURES = ["acousticness", "danceability", "energy", "instrumentalness", "key", "liveness",
            "loudness", "mode", "speechiness", "tempo", "valence"]

DDL = """
CREATE TABLE IF NOT EXISTS radio.spotify_audio_features (
    spotify_track_id  text PRIMARY KEY,
    found             boolean NOT NULL,
    reccobeats_id     text,
    isrc              text,
    acousticness      numeric,
    danceability      numeric,
    energy            numeric,
    instrumentalness  numeric,
    key               integer,
    liveness          numeric,
    loudness          numeric,
    mode              integer,
    speechiness       numeric,
    tempo             numeric,
    valence           numeric,
    fetched_at        timestamptz NOT NULL DEFAULT now()
);
"""

UPSERT = f"""
INSERT INTO radio.spotify_audio_features (
    spotify_track_id, found, reccobeats_id, isrc, {", ".join(FEATURES)}
) VALUES %s
ON CONFLICT (spotify_track_id) DO UPDATE SET
    found = EXCLUDED.found,
    reccobeats_id = EXCLUDED.reccobeats_id,
    isrc = EXCLUDED.isrc,
    {", ".join(f"{f} = EXCLUDED.{f}" for f in FEATURES)},
    fetched_at = now()
"""


def pending_ids(cur, limit):
    cur.execute(
        """
        SELECT DISTINCT s.spotify_track_id
        FROM radio.spotify_tracks s
        WHERE s.found
          AND NOT EXISTS (SELECT 1 FROM radio.spotify_audio_features f
                          WHERE f.spotify_track_id = s.spotify_track_id)
        ORDER BY s.spotify_track_id
        """ + (" LIMIT %s" if limit else ""),
        (limit,) if limit else None,
    )
    return [row[0] for row in cur.fetchall()]


def row_for(track_id, feats):
    if feats is None:
        return (track_id, False, None, None) + (None,) * len(FEATURES)
    return (track_id, True, feats.get("id"), feats.get("isrc")) + tuple(feats.get(f) for f in FEATURES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    ids = pending_ids(cur, args.limit)
    print(f"{len(ids)} tracks to fetch features for", file=sys.stderr)

    done = found = 0
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        features = fetch_audio_features(chunk)
        execute_values(cur, UPSERT, [row_for(t, features.get(t)) for t in chunk])
        done += len(chunk)
        found += len(features)
        print(f"{done}/{len(ids)} tracks, {found} with features", file=sys.stderr)
    print(f"finished: {done} tracks, {found} with features", file=sys.stderr)


if __name__ == "__main__":
    main()
