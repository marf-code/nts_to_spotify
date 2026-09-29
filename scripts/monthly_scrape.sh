#!/bin/sh
# Refresh radio.nts_shows / nts_episodes / nts_tracks from NTS, then match and enrich any new tracks.
set -eu

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-$HOME/.pyenv/versions/3.12.3/bin/python}"
export PATH="/usr/local/bin:$PATH"

echo "=== monthly scrape started $(date)"
docker compose -f db/docker-compose.yml up -d

"$PYTHON" scripts/list_all_episodes.py .scratch/nts_episodes.csv
"$PYTHON" scripts/harvest_episodes.py .scratch/nts_episodes.csv -o .scratch/nts_episodes_full.csv
"$PYTHON" scripts/list_all_shows.py .scratch/nts_shows.csv --episodes .scratch/nts_episodes_full.csv
"$PYTHON" scripts/load_nts_episodes.py .scratch/nts_episodes_full.csv --shows .scratch/nts_shows.csv
"$PYTHON" scripts/harvest_tracklists.py -o .scratch/nts_tracklists.csv
"$PYTHON" scripts/load_nts_tracks.py .scratch/nts_tracklists.csv
"$PYTHON" scripts/locate_spotify_tracks.py
"$PYTHON" scripts/fetch_audio_features.py

echo "=== monthly scrape finished $(date)"
