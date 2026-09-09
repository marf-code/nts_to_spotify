#!/usr/bin/env bash
# Refresh the radio schema + data seeds used when the Postgres volume is created from scratch.
set -euo pipefail
cd "$(dirname "$0")"
docker exec spotify-account-postgres pg_dump -U spotify_user -d spotify_account_data --schema-only -n radio --no-owner --no-privileges > init/02-radio_schema.sql
docker exec spotify-account-postgres pg_dump -U spotify_user -d spotify_account_data --data-only  -n radio --no-owner --no-privileges > init/03-radio_data.sql
ls -lh init/
