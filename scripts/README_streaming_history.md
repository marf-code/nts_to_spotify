# Import Spotify Extended Streaming History

Run from the repository root with a Python environment containing `psycopg2`.
The script reuses `load_enriched_tracks.DB_CONFIG` and its `SPOTIFY_DB_*`
environment variables. It does not load, request, or refresh Spotify credentials.

```sh
python scripts/import_streaming_history.py '/path/to/Spotify Extended Streaming History' --dry-run
python scripts/import_streaming_history.py '/path/to/Spotify Extended Streaming History' --apply
```

The default is a database-enforced read-only preview. A directory loads only
`Streaming_History_Audio_*.json`; an individual JSON file can also be supplied.
Extract ZIP archives first and retain the originals. Video history is not included
when loading a directory.

`--apply` inserts new events in one transaction and takes a table write lock,
with a 10-second lock timeout, to prevent concurrent imports from racing. Failed
transactions roll back. It never updates or deletes existing rows, changes the
schema, or modifies source files. Existing duplicate rows remain untouched.

Overlap matching uses timestamp (normalized to UTC), username, Spotify track URI,
and milliseconds played, treating missing values as equal. For events without a
track URI, episode URI/name and track/artist names distinguish different content.
The first occurrence of an identical event key in the input is retained. Separate
plays with exactly the same key cannot be distinguished and are counted as one.
If another importer provides usernames for records that previously lacked them,
those records have different keys; review the dry-run before applying.

Tests use session-local temporary PostgreSQL tables and roll back on cleanup:

```sh
python -m unittest discover -s tests -p 'test_streaming_history.py' -v
```

This imports downloaded history only. It does not request exports, schedule jobs,
collect recent plays through the API, or import Shazam recognition history.
