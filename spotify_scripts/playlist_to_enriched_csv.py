"""Export a Spotify playlist as an enriched-tracks CSV (Chosic-style).

Spotify removed the audio-features endpoint for small apps in Nov 2024, so
the valence/energy/danceability numbers come from ReccoBeats
(https://reccobeats.com) — a free, keyless API that serves the classic
Spotify audio-features schema for Spotify track IDs, in batches of 40.

Everything else (title, artist, album, ISRC, popularity, genres, label)
comes from the regular Spotify Web API, which still works for playlist
reads. Public playlists need no login (client-credentials); private ones
need a user access token.

The output CSV has the exact column shape load_enriched_tracks.py ingests:

    #,Song,Artist,BPM,Camelot,Energy,Added At,Duration,Popularity,Genres,
    Parent Genres,Album,Album Date,Dance,Acoustic,Instrumental,Valence,
    Speech,Live,Loud (Db),Key,Time Signature,Spotify Track Id,Label,ISRC,Explicit

Usage:
    python playlist_to_enriched_csv.py --playlist <url|uri|id> [--output out.csv]
        [--access-token TOKEN] [--skip-details]

Notes:
  * ReccoBeats does not know every track. For the misses, the track's 30s
    preview clip is fetched from Deezer (matched by ISRC, no auth needed) and
    uploaded to ReccoBeats' analysis endpoint, which computes the same
    features from the audio itself (except key/mode). Tracks that neither
    source covers get blank feature columns; a summary is printed at the end.
  * Time Signature is not provided by ReccoBeats and is left blank.
  * --skip-details skips the per-artist/per-album Spotify lookups that fill
    Genres, Parent Genres and Label (the slowest part on big playlists).
  * --no-preview-fallback skips the Deezer/upload second pass.
"""

import argparse
import base64
import csv
import os
import re
import sys
import time

import requests

from dedup_playlist import parse_playlist_id
from spotify_v2 import _request_with_retry, client_id, client_secret

RECCOBEATS_URL = 'https://api.reccobeats.com/v1/audio-features'
RECCOBEATS_ANALYSIS_URL = 'https://api.reccobeats.com/v1/analysis/audio-features'
RECCOBEATS_BATCH = 40  # documented max ids per request
SPOTIFY_DETAIL_DELAY = 0.15  # pacing for per-artist/per-album lookups

CSV_COLUMNS = [
    '#', 'Song', 'Artist', 'BPM', 'Camelot', 'Energy', 'Added At',
    'Duration', 'Popularity', 'Genres', 'Parent Genres', 'Album',
    'Album Date', 'Dance', 'Acoustic', 'Instrumental', 'Valence',
    'Speech', 'Live', 'Loud (Db)', 'Key', 'Time Signature',
    'Spotify Track Id', 'Label', 'ISRC', 'Explicit',
]

KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Camelot wheel position for each pitch class, by mode (1=major, 0=minor).
CAMELOT_MAJOR = {0: '8B', 1: '3B', 2: '10B', 3: '5B', 4: '12B', 5: '7B',
                 6: '2B', 7: '9B', 8: '4B', 9: '11B', 10: '6B', 11: '1B'}
CAMELOT_MINOR = {0: '5A', 1: '12A', 2: '7A', 3: '2A', 4: '9A', 5: '4A',
                 6: '11A', 7: '6A', 8: '1A', 9: '8A', 10: '3A', 11: '10A'}

# Keyword -> parent genre, checked in order (first match wins per genre).
# A rough stand-in for Chosic's genre hierarchy.
PARENT_GENRE_RULES = [
    (('hip hop', 'rap', 'trap', 'drill', 'grime', 'boom bap'), 'Hip Hop'),
    (('country', 'red dirt', 'bluegrass', 'honky tonk'), 'Country'),
    (('house', 'techno', 'electro', 'trance', 'dubstep', 'garage', 'jungle',
      'drum and bass', 'ambient', 'idm', 'downtempo', 'breakbeat', 'edm',
      'rave', 'synth', 'electronic', 'dance', 'bass music'), 'Electronic'),
    (('r&b', 'rnb', 'soul', 'funk', 'disco', 'motown', 'quiet storm',
      'new jack'), 'R&B'),
    (('jazz', 'bossa', 'swing', 'bebop', 'big band'), 'Jazz'),
    (('metal', 'metalcore', 'thrash'), 'Metal'),
    (('rock', 'punk', 'grunge', 'shoegaze', 'indie', 'psych',
      'new wave', 'post-'), 'Rock'),
    (('folk', 'singer-songwriter', 'americana', 'acoustic'), 'Folk'),
    (('classical', 'orchestra', 'baroque', 'opera', 'chamber'), 'Classical'),
    (('reggae', 'dub', 'ska', 'dancehall'), 'Reggae'),
    (('latin', 'salsa', 'cumbia', 'reggaeton', 'bachata', 'samba',
      'mpb', 'bolero'), 'Latin'),
    (('blues',), 'Blues'),
    (('gospel', 'christian'), 'Gospel'),
    (('soundtrack', 'score', 'video game'), 'Soundtrack'),
    (('afro', 'highlife', 'amapiano', 'world'), 'World'),
    (('pop',), 'Pop'),
]


def get_client_credentials_token():
    """App-only token — enough to read public playlists, artists and albums."""
    auth_header = base64.b64encode(
        f'{client_id}:{client_secret}'.encode('ascii')
    ).decode('ascii')
    resp = _request_with_retry(
        'POST',
        'https://accounts.spotify.com/api/token',
        headers={'Authorization': f'Basic {auth_header}'},
        data={'grant_type': 'client_credentials'},
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def fetch_playlist_tracks(access_token, playlist_id):
    """Return (playlist_name, tracks) with everything the CSV needs."""
    headers = {'Authorization': f'Bearer {access_token}'}

    resp = _request_with_retry(
        'GET',
        f'https://api.spotify.com/v1/playlists/{playlist_id}',
        headers=headers,
        params={'fields': 'name'},
    )
    if resp.status_code == 404:
        raise SystemExit(
            'Playlist not found. If it is private, pass --access-token with a '
            'user token (public playlists need no login).'
        )
    resp.raise_for_status()
    name = resp.json()['name']

    tracks = []
    skipped = 0
    # Apps created after Spotify's 2026 API changes only get /items (entry key 'item');
    # older apps may still need /tracks (entry key 'track').
    track_fields = ('(id,type,name,duration_ms,explicit,popularity,external_ids(isrc),'
                    'artists(id,name),album(id,name,release_date))')
    for endpoint, key in (('items', 'item'), ('tracks', 'track')):
        url = f'https://api.spotify.com/v1/playlists/{playlist_id}/{endpoint}'
        params = {'limit': 100, 'fields': f'next,items(added_at,is_local,{key}{track_fields})'}
        resp = _request_with_retry('GET', url, headers=headers, params=params)
        if resp.status_code not in (403, 404):
            break
    while url:
        resp.raise_for_status()
        data = resp.json()
        for item in data.get('items', []):
            track = item.get(key)
            if not track or item.get('is_local') or track.get('type') != 'track' \
                    or not track.get('id'):
                skipped += 1
                continue
            tracks.append({
                'id': track['id'],
                'name': track.get('name', ''),
                'artists': track.get('artists', []),
                'album': track.get('album', {}) or {},
                'duration_ms': track.get('duration_ms'),
                'explicit': track.get('explicit'),
                'popularity': track.get('popularity'),
                'isrc': (track.get('external_ids') or {}).get('isrc', ''),
                'added_at': (item.get('added_at') or '')[:10],
            })
        url = data.get('next')
        if url:
            # `next` already carries limit/fields/offset
            resp = _request_with_retry('GET', url, headers=headers)
        print(f'  fetched {len(tracks)} tracks...', flush=True)

    if skipped:
        print(f'  ignoring {skipped} local/unavailable items', flush=True)
    return name, tracks


def fetch_audio_features(track_ids):
    """Query ReccoBeats in batches of 40; return {spotify_id: features}."""
    features = {}
    for i in range(0, len(track_ids), RECCOBEATS_BATCH):
        batch = track_ids[i:i + RECCOBEATS_BATCH]
        resp = _request_with_retry(
            'GET', RECCOBEATS_URL, params={'ids': ','.join(batch)}
        )
        resp.raise_for_status()
        for item in resp.json().get('content', []):
            # Tracks ReccoBeats doesn't know are silently omitted, so match
            # results back to Spotify IDs via the href, never by position.
            m = re.search(r'open\.spotify\.com/track/([A-Za-z0-9]+)',
                          item.get('href') or '')
            if m:
                features[m.group(1)] = item
        print(f'  audio features {len(features)}/{min(i + RECCOBEATS_BATCH, len(track_ids))}...',
              flush=True)
        time.sleep(0.5)
    return features


def fetch_features_via_preview(tracks):
    """Fallback for tracks ReccoBeats doesn't know: analyze the audio itself.

    Deezer serves 30-second preview clips keyed by ISRC with no auth; the
    clip is uploaded to ReccoBeats' analysis endpoint, which returns the same
    feature schema computed from the audio (it does not include key/mode).
    Returns {spotify_id: features}.
    """
    features = {}
    for n, track in enumerate(tracks, 1):
        if not track['isrc']:
            continue
        try:
            resp = _request_with_retry(
                'GET', f'https://api.deezer.com/track/isrc:{track["isrc"]}'
            )
            preview_url = resp.json().get('preview') if resp.ok else None
            if not preview_url:
                continue
            preview = requests.get(preview_url, timeout=20).content
            resp = _request_with_retry(
                'POST', RECCOBEATS_ANALYSIS_URL,
                files={'audioFile': ('preview.mp3', preview, 'audio/mpeg')},
            )
            if resp.ok:
                features[track['id']] = resp.json()
        except Exception as e:
            print(f'  preview analysis failed for {track["name"]}: {e}', flush=True)
        if n % 10 == 0:
            print(f'  analyzed {n}/{len(tracks)} previews '
                  f'({len(features)} recovered)...', flush=True)
        time.sleep(0.5)
    return features


def fetch_artist_genres(access_token, artist_ids):
    """Return {artist_id: [genres]} via per-artist lookups (batch API is gone)."""
    headers = {'Authorization': f'Bearer {access_token}'}
    genres = {}
    for n, artist_id in enumerate(artist_ids, 1):
        resp = _request_with_retry(
            'GET', f'https://api.spotify.com/v1/artists/{artist_id}',
            headers=headers,
        )
        if resp.ok:
            genres[artist_id] = resp.json().get('genres', [])
        if n % 25 == 0:
            print(f'  artist genres {n}/{len(artist_ids)}...', flush=True)
        time.sleep(SPOTIFY_DETAIL_DELAY)
    return genres


def fetch_album_labels(access_token, album_ids):
    """Return {album_id: label} via per-album lookups."""
    headers = {'Authorization': f'Bearer {access_token}'}
    labels = {}
    for n, album_id in enumerate(album_ids, 1):
        resp = _request_with_retry(
            'GET', f'https://api.spotify.com/v1/albums/{album_id}',
            headers=headers,
        )
        if resp.ok:
            labels[album_id] = resp.json().get('label', '')
        if n % 25 == 0:
            print(f'  album labels {n}/{len(album_ids)}...', flush=True)
        time.sleep(SPOTIFY_DETAIL_DELAY)
    return labels


def parent_genres(genre_list):
    parents = []
    for genre in genre_list:
        g = genre.lower()
        for keywords, parent in PARENT_GENRE_RULES:
            if any(k in g for k in keywords):
                if parent not in parents:
                    parents.append(parent)
                break
    return ', '.join(parents)


def pct(value):
    """Spotify's 0-1 features -> the 0-100 integers Chosic exports."""
    return '' if value is None else round(value * 100)


def format_duration(ms):
    if not ms:
        return ''
    total_seconds = round(ms / 1000)
    return f'{total_seconds // 60:02d}:{total_seconds % 60:02d}'


def build_row(index, track, feats, genres_by_artist, labels_by_album):
    genre_list = []
    for artist in track['artists']:
        for g in genres_by_artist.get(artist.get('id'), []):
            if g not in genre_list:
                genre_list.append(g)

    key = feats.get('key')
    mode = feats.get('mode')
    has_key = key is not None and key >= 0
    camelot_map = CAMELOT_MAJOR if mode == 1 else CAMELOT_MINOR

    return {
        '#': index,
        'Song': track['name'],
        'Artist': ', '.join(a.get('name', '') for a in track['artists']),
        'BPM': round(feats['tempo']) if feats.get('tempo') else '',
        'Camelot': camelot_map[key] if has_key else '',
        'Energy': pct(feats.get('energy')),
        'Added At': track['added_at'],
        'Duration': format_duration(track['duration_ms']),
        'Popularity': track['popularity'] if track['popularity'] is not None else '',
        'Genres': ', '.join(genre_list),
        'Parent Genres': parent_genres(genre_list),
        'Album': track['album'].get('name', ''),
        'Album Date': track['album'].get('release_date', ''),
        'Dance': pct(feats.get('danceability')),
        'Acoustic': pct(feats.get('acousticness')),
        'Instrumental': pct(feats.get('instrumentalness')),
        'Valence': pct(feats.get('valence')),
        'Speech': pct(feats.get('speechiness')),
        'Live': pct(feats.get('liveness')),
        'Loud (Db)': round(feats['loudness']) if feats.get('loudness') is not None else '',
        'Key': KEY_NAMES[key] if has_key else '',
        'Time Signature': '',  # not provided by ReccoBeats
        'Spotify Track Id': track['id'],
        'Label': labels_by_album.get(track['album'].get('id'), ''),
        'ISRC': track['isrc'],
        'Explicit': 'yes' if track['explicit'] else 'no',
    }


def safe_filename(name):
    cleaned = re.sub(r'[^\w\s-]', '', name).strip()
    return re.sub(r'\s+', '_', cleaned).lower() or 'playlist'


def main():
    parser = argparse.ArgumentParser(
        description='Export a Spotify playlist as an enriched-tracks CSV.'
    )
    parser.add_argument('--playlist', required=True, help='Playlist URL, URI, or ID')
    parser.add_argument('--output', help='Output CSV path (default: <playlist name>.csv)')
    parser.add_argument(
        '--output-dir',
        help='Directory for the default-named CSV (ignored if --output is given)',
    )
    parser.add_argument(
        '--access-token',
        default=os.getenv('SPOTIFY_ACCESS_TOKEN'),
        help='Spotify user access token, needed only for private playlists. '
             'Can also be set via SPOTIFY_ACCESS_TOKEN env var.',
    )
    parser.add_argument(
        '--skip-details',
        action='store_true',
        help='Skip the per-artist/per-album lookups for Genres and Label '
             '(much faster on big playlists).',
    )
    parser.add_argument(
        '--no-preview-fallback',
        action='store_true',
        help='Do not analyze Deezer preview clips for tracks ReccoBeats '
             'does not already know.',
    )
    args = parser.parse_args()

    playlist_id = parse_playlist_id(args.playlist)
    access_token = args.access_token or get_client_credentials_token()

    print(f'Fetching playlist {playlist_id}...', flush=True)
    name, tracks = fetch_playlist_tracks(access_token, playlist_id)
    print(f'"{name}" has {len(tracks)} tracks', flush=True)
    if not tracks:
        raise SystemExit('Playlist has no tracks to export.')

    print('Fetching audio features from ReccoBeats...', flush=True)
    features = fetch_audio_features([t['id'] for t in tracks])

    missing = [t for t in tracks if t['id'] not in features]
    if missing and not args.no_preview_fallback:
        print(f'Analyzing preview clips for {len(missing)} tracks '
              'ReccoBeats does not know...', flush=True)
        recovered = fetch_features_via_preview(missing)
        features.update(recovered)
        print(f'  recovered {len(recovered)}/{len(missing)} from previews',
              flush=True)

    genres_by_artist = {}
    labels_by_album = {}
    if not args.skip_details:
        artist_ids = list(dict.fromkeys(
            a['id'] for t in tracks for a in t['artists'] if a.get('id')
        ))
        album_ids = list(dict.fromkeys(
            t['album']['id'] for t in tracks if t['album'].get('id')
        ))
        print(f'Fetching genres for {len(artist_ids)} artists...', flush=True)
        genres_by_artist = fetch_artist_genres(access_token, artist_ids)
        print(f'Fetching labels for {len(album_ids)} albums...', flush=True)
        labels_by_album = fetch_album_labels(access_token, album_ids)

    output = args.output or f'{safe_filename(name)}.csv'
    if args.output_dir and not args.output:
        os.makedirs(args.output_dir, exist_ok=True)
        output = os.path.join(args.output_dir, output)
    with open(output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for i, track in enumerate(tracks, 1):
            writer.writerow(build_row(
                i, track, features.get(track['id'], {}),
                genres_by_artist, labels_by_album,
            ))

    missing = [t for t in tracks if t['id'] not in features]
    print(f'\nWrote {len(tracks)} tracks to {output}')
    print(f'Audio features found for {len(tracks) - len(missing)}/{len(tracks)} tracks.')
    if missing:
        print('No features for:')
        for t in missing[:20]:
            artists = ', '.join(a.get('name', '') for a in t['artists'])
            print(f'  - {t["name"]} — {artists}')
        if len(missing) > 20:
            print(f'  ... and {len(missing) - 20} more')


if __name__ == '__main__':
    main()
