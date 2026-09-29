#!/usr/bin/env python3
"""
Refresh radio.enriched_tracks from every playlist on your Spotify account.

Each playlist is exported with spotify_scripts/playlist_to_enriched_csv.py and
loaded with load_enriched_tracks.py --replace, so its rows always match the
playlist as it is now. Only playlists you own are synced unless
--include-followed is passed.

Runs under its own Spotify app so it never shares a rate limit with
locate_spotify_tracks.py. Put that app's credentials in .env:

    SPOTIFY_SYNC_CLIENT_ID=...
    SPOTIFY_SYNC_CLIENT_SECRET=...
    SPOTIFY_SYNC_REDIRECT_URI=http://127.0.0.1:8000/callback/   (must match the app's settings)

The first run asks you to log in and saves SPOTIFY_SYNC_REFRESH_TOKEN to .env;
later runs refresh from it and need no browser.

Apps created after Spotify's 2026 API changes get no genres, labels or
popularity, so those columns arrive blank; the run ends with
merge_chosic_fields.py, which fills them for tracks seen in a Chosic export.

Usage:
    python scripts/sync_my_playlists.py [--include-followed] [--only NAME ...] [--dry-run]
        [--no-preview-fallback]
"""

import argparse
import os
import subprocess
import sys
import time

import requests
from dotenv import set_key

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "spotify_scripts"))
from spotify_v2 import _request_with_retry, get_user_token  # noqa: E402

SCOPE = "playlist-read-private playlist-read-collaborative"
EXPORT_DIR = os.path.join(ROOT, ".scratch", "my_playlists")
ENV_PATH = os.path.join(ROOT, ".env")


class UserToken:
    """Access token for the sync app, refreshed from the saved refresh token."""

    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.refresh_token = os.getenv("SPOTIFY_SYNC_REFRESH_TOKEN")
        self.expires_at = 0
        if not self.refresh_token:
            self._store(get_user_token(
                scope=SCOPE, app_id=app_id, app_secret=app_secret,
                app_redirect_uri=os.getenv("SPOTIFY_SYNC_REDIRECT_URI", "http://127.0.0.1:8000/callback/"),
            ))

    def _store(self, data):
        self.access_token = data["access_token"]
        self.expires_at = time.time() + data["expires_in"] - 300
        # Spotify sometimes rotates the refresh token; keep .env on the latest one.
        if data.get("refresh_token") and data["refresh_token"] != self.refresh_token:
            self.refresh_token = data["refresh_token"]
            set_key(ENV_PATH, "SPOTIFY_SYNC_REFRESH_TOKEN", self.refresh_token, quote_mode="never")

    def get(self):
        if time.time() >= self.expires_at:
            resp = requests.post(
                "https://accounts.spotify.com/api/token", auth=(self.app_id, self.app_secret),
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token}, timeout=30,
            )
            resp.raise_for_status()
            self._store(resp.json())
        return self.access_token


def my_playlists(token, include_followed):
    headers = {"Authorization": f"Bearer {token}"}
    resp = _request_with_retry("GET", "https://api.spotify.com/v1/me", headers=headers)
    resp.raise_for_status()
    me = resp.json()["id"]

    playlists = []
    url = "https://api.spotify.com/v1/me/playlists?limit=50"
    while url:
        resp = _request_with_retry("GET", url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        for p in data["items"]:
            if p and p["items"]["total"] and (include_followed or p["owner"]["id"] == me):
                playlists.append(p)
        url = data.get("next")
    return playlists


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("--include-followed", action="store_true",
                        help="Also sync playlists you follow but don't own")
    parser.add_argument("--only", nargs="+", metavar="NAME",
                        help="Sync only playlists with these exact names")
    parser.add_argument("--dry-run", action="store_true", help="List playlists and exit")
    parser.add_argument("--no-preview-fallback", action="store_true")
    args = parser.parse_args()

    app_id = os.getenv("SPOTIFY_SYNC_CLIENT_ID")
    app_secret = os.getenv("SPOTIFY_SYNC_CLIENT_SECRET")
    if not app_id or not app_secret:
        sys.exit("Set SPOTIFY_SYNC_CLIENT_ID and SPOTIFY_SYNC_CLIENT_SECRET in .env (see --help).")
    token = UserToken(app_id, app_secret)

    playlists = my_playlists(token.get(), args.include_followed)
    if args.only:
        playlists = [p for p in playlists if p["name"] in args.only]
    print(f"{len(playlists)} playlists to sync", flush=True)
    for p in playlists:
        print(f"  {p['name']} ({p['items']['total']} tracks)")
    if args.dry_run:
        return

    os.makedirs(EXPORT_DIR, exist_ok=True)
    failed = []
    for i, p in enumerate(playlists, 1):
        print(f"\n[{i}/{len(playlists)}] {p['name']}", flush=True)
        csv_path = os.path.join(EXPORT_DIR, f"{p['id']}.csv")
        export = [sys.executable, os.path.join(ROOT, "spotify_scripts", "playlist_to_enriched_csv.py"),
                  "--playlist", p["id"], "--output", csv_path, "--skip-details"]
        if args.no_preview_fallback:
            export.append("--no-preview-fallback")
        load = [sys.executable, os.path.join(ROOT, "load_enriched_tracks.py"), csv_path,
                "--playlist-name", p["name"], "--replace"]
        # Passed via env rather than argv so the token doesn't show up in ps.
        env = {**os.environ, "SPOTIFY_ACCESS_TOKEN": token.get()}
        if subprocess.run(export, env=env).returncode or subprocess.run(load).returncode:
            failed.append(p["name"])

    subprocess.run([sys.executable, os.path.join(HERE, "merge_chosic_fields.py")])
    print(f"\nsynced {len(playlists) - len(failed)}/{len(playlists)} playlists")
    if failed:
        print("failed: " + ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
