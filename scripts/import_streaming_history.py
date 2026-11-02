#!/usr/bin/env python3
"""Import Spotify Extended Streaming History; preview by default, --apply to insert."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from load_enriched_tracks import DB_CONFIG

COLUMNS = (
    'ts', 'username', 'platform', 'ms_played', 'conn_country',
    'ip_addr_decrypted', 'user_agent_decrypted', 'master_metadata_track_name',
    'master_metadata_album_artist_name', 'master_metadata_album_album_name',
    'spotify_track_uri', 'episode_name', 'episode_show_name', 'spotify_episode_uri',
    'reason_start', 'reason_end', 'shuffle', 'skipped', 'offline',
    'offline_timestamp', 'incognito_mode',
)


def event_key(row):
    fallback = None if row['spotify_track_uri'] else (
        row['spotify_episode_uri'], row['episode_name'],
        row['master_metadata_track_name'], row['master_metadata_album_artist_name'],
    )
    return (row['ts'], row['username'], row['spotify_track_uri'], row['ms_played'], fallback)


def read_export(path):
    files = sorted(path.glob('Streaming_History_Audio_*.json')) if path.is_dir() else [path]
    if not files:
        raise ValueError('No Streaming_History_Audio_*.json files found')
    rows = []
    for file in files:
        records = json.loads(file.read_text(encoding='utf-8-sig'))
        if not isinstance(records, list):
            raise ValueError(f'{file.name}: expected a JSON array')
        for index, record in enumerate(records, 1):
            try:
                row = {column: record.get(column) for column in COLUMNS}
                timestamp = datetime.fromisoformat(row['ts'].replace('Z', '+00:00'))
                if timestamp.tzinfo is None:
                    raise ValueError('timestamp has no timezone')
                row['ts'] = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
                if type(row['ms_played']) is not int or row['ms_played'] < 0:
                    raise ValueError('invalid ms_played')
                hash(event_key(row))
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError(f'{file.name}: invalid event at row {index}') from error
            rows.append(row)
    return rows, len(files)


def import_rows(conn, rows, apply=False, table=('public', 'extended_streaming_history')):
    target = sql.Identifier(*table)
    columns = sql.SQL(', ').join(map(sql.Identifier, COLUMNS))
    unique = {}
    for row in rows:
        unique.setdefault(event_key(row), row)
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        if apply:
            cursor.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(target))
        existing = set()
        if rows:
            cursor.execute(
                sql.SQL('SELECT {} FROM {} WHERE ts BETWEEN %s AND %s').format(columns, target),
                (min(row['ts'] for row in rows), max(row['ts'] for row in rows)),
            )
            while batch := cursor.fetchmany(5000):
                existing.update(event_key(dict(zip(COLUMNS, values))) for values in batch)
        new = [row for key, row in unique.items() if key not in existing]
        if apply and new:
            execute_values(cursor, sql.SQL('INSERT INTO {} ({}) VALUES %s').format(target, columns),
                           [tuple(row[column] for column in COLUMNS) for row in new], page_size=1000)
    return {'input_rows': len(rows), 'repeated_input_events': len(rows) - len(unique),
            'already_present': len(unique) - len(new), 'new_events': len(new),
            'inserted': len(new) if apply else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, help='Extracted export directory or one history JSON file')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Insert new events in one transaction')
    mode.add_argument('--dry-run', action='store_true', help='Preview only (the default)')
    args = parser.parse_args()
    rows, files = read_export(args.path)
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        conn.set_session(readonly=not args.apply, isolation_level='READ COMMITTED' if args.apply else 'REPEATABLE READ')
        with conn:
            result = import_rows(conn, rows, apply=args.apply)
        print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'files': files, **result}, indent=2))
    finally:
        conn.close()


if __name__ == '__main__':
    main()
