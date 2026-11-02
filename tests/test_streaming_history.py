import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import import_streaming_history as importer


def event(**values):
    row = dict.fromkeys(importer.COLUMNS)
    row.update(ts=datetime(2026, 1, 1), ms_played=1234, spotify_track_uri='spotify:track:test')
    row.update(values)
    return row


class ExportTests(unittest.TestCase):
    def test_normalizes_timezone_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Streaming_History_Audio_test.json'
            content = json.dumps([{'ts': '2026-01-01T01:00:00+01:00', 'ms_played': 1}])
            path.write_text(content)
            rows, count = importer.read_export(Path(directory))
            self.assertEqual(count, 1)
            self.assertEqual(rows[0]['ts'], datetime(2026, 1, 1))
            self.assertEqual(path.read_text(), content)

    def test_invalid_event_fails_before_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            path.write_text('[{"ts":"invalid","ms_played":10}]')
            with self.assertRaises(ValueError):
                importer.read_export(path)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = importer.psycopg2.connect(**importer.DB_CONFIG)
        with self.conn.cursor() as cursor:
            cursor.execute('CREATE TEMP TABLE history_fixture (LIKE public.extended_streaming_history)')
            cursor.execute('ALTER TABLE pg_temp.history_fixture ALTER COLUMN id DROP NOT NULL')
        self.table = ('pg_temp', 'history_fixture')

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def run_import(self, rows, apply=True):
        return importer.import_rows(self.conn, rows, apply=apply, table=self.table)

    def count(self):
        with self.conn.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM pg_temp.history_fixture')
            return cursor.fetchone()[0]

    def test_null_username_overlapping_imports(self):
        first = event()
        second = event(ts=datetime(2026, 1, 2))
        self.assertEqual(self.run_import([first, first])['inserted'], 1)
        result = self.run_import([first, second])
        self.assertEqual((result['already_present'], result['inserted']), (1, 1))
        self.assertEqual(self.run_import([first, second])['inserted'], 0)
        self.assertEqual(self.count(), 2)

    def test_dry_run_does_not_insert(self):
        self.assertEqual(self.run_import([event()], apply=False)['new_events'], 1)
        self.assertEqual(self.count(), 0)

    def test_distinct_null_uri_episodes_preserved(self):
        rows = [event(spotify_track_uri=None, spotify_episode_uri=f'spotify:episode:{n}') for n in (1, 2)]
        self.assertEqual(self.run_import(rows)['inserted'], 2)
        self.assertEqual(self.run_import(rows)['inserted'], 0)

    def test_different_users_and_durations_preserved(self):
        rows = [event(), event(username='other'), event(ms_played=1235)]
        self.assertEqual(self.run_import(rows)['inserted'], 3)

    def test_existing_duplicate_rows_unchanged(self):
        self.run_import([event()])
        with self.conn.cursor() as cursor:
            cursor.execute('INSERT INTO pg_temp.history_fixture SELECT * FROM pg_temp.history_fixture')
        self.assertEqual(self.run_import([event()])['inserted'], 0)
        self.assertEqual(self.count(), 2)


if __name__ == '__main__':
    unittest.main()
