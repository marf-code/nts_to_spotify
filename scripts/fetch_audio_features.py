#!/usr/bin/env python3
"""
Fetch audio features (valence, energy, danceability, ...) for every track in
radio.track that has none yet, and store them on radio.track.

Spotify's own audio-features endpoint is closed to new apps, so the numbers
come from ReccoBeats, which serves the same schema keyed by Spotify track ID.
Every track asked about gets features_fetched_at, so tracks ReccoBeats doesn't
know are not retried, a stopped run resumes, and re-running picks up tracks
added since the last run.

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

UPDATE = f"""
UPDATE radio.track t SET
    reccobeats_id = COALESCE(v.reccobeats_id, t.reccobeats_id),
    isrc = COALESCE(t.isrc, v.isrc),
    {", ".join(f"{f} = COALESCE(v.{f}, t.{f})" for f in FEATURES)},
    features_fetched_at = now(),
    updated_at = now()
FROM (VALUES %s) AS v (spotify_track_id, reccobeats_id, isrc, {", ".join(FEATURES)})
WHERE t.spotify_track_id = v.spotify_track_id
"""
# VALUES rows are untyped, so cast them to the radio.track column types.
TEMPLATE = "(%s, %s, %s, " + ", ".join(
    "%s::integer" if f in ("key", "mode") else "%s::numeric" for f in FEATURES) + ")"


def pending_ids(cur, limit):
    cur.execute(
        "SELECT spotify_track_id FROM radio.track "
        "WHERE features_fetched_at IS NULL AND energy IS NULL ORDER BY spotify_track_id"
        + (" LIMIT %s" if limit else ""),
        (limit,) if limit else None,
    )
    return [row[0] for row in cur.fetchall()]


def row_for(track_id, feats):
    if feats is None:
        return (track_id, None, None) + (None,) * len(FEATURES)
    return (track_id, feats.get("id"), feats.get("isrc")) + tuple(feats.get(f) for f in FEATURES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    ids = pending_ids(cur, args.limit)
    print(f"{len(ids)} tracks to fetch features for", file=sys.stderr)

    done = found = 0
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        features = fetch_audio_features(chunk)
        execute_values(cur, UPDATE, [row_for(t, features.get(t)) for t in chunk], template=TEMPLATE)
        done += len(chunk)
        found += len(features)
        print(f"{done}/{len(ids)} tracks, {found} with features", file=sys.stderr)
    print(f"finished: {done} tracks, {found} with features", file=sys.stderr)


if __name__ == "__main__":
    main()
