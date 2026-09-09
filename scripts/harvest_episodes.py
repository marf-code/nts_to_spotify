#!/usr/bin/env python3
"""
Harvest the full episode record for every NTS episode, including location.

Location is an episode-level field. A show's own location_long is often blank
(umbrella shows like "guests") or reflects only one of the cities its episodes
came from, so any location data has to be collected per episode.

Reads the episode list produced by list_all_episodes.py, pages
/api/v2/shows/<slug>/episodes for each show, then fills the gap for shows
past that endpoint's offset-1000 ceiling by fetching those episodes singly.

Usage:
    python scripts/harvest_episodes.py [episodes.csv] [-o out.csv] [--workers N]
"""

import argparse
import csv
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote

import requests

PAGE = 12          # /shows/<slug>/episodes ignores larger limits
MAX_OFFSET = 1000  # server rejects anything past this
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

FIELDS = ["show_alias", "episode_alias", "show_name", "location", "broadcast", "genres", "url"]


def make_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=64))
    return session


def row_from(episode):
    show = episode.get("show_alias") or ""
    alias = episode.get("episode_alias") or ""
    return {
        "show_alias": show,
        "episode_alias": alias,
        "show_name": episode.get("name") or "",
        "location": episode.get("location_long") or episode.get("location_short") or "",
        "broadcast": episode.get("broadcast") or "",
        "genres": "; ".join(g.get("value", "") for g in (episode.get("genres") or [])),
        "url": f"https://www.nts.live/shows/{quote(show)}/episodes/{quote(alias)}",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("episodes_csv", nargs="?", default=".scratch/nts_episodes.csv")
    parser.add_argument("-o", "--out", default=".scratch/nts_episodes_full.csv")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    wanted = {}
    with open(args.episodes_csv) as fh:
        for row in csv.DictReader(fh):
            wanted[(unquote(row["show_alias"]), unquote(row["episode_alias"]))] = row["url"]
    per_show = defaultdict(int)
    for show, _ in wanted:
        per_show[show] += 1
    print(f"{len(wanted)} episodes across {len(per_show)} shows", file=sys.stderr)

    session = make_session()
    found = {}

    def fetch_page(job):
        show, offset = job
        url = f"https://www.nts.live/api/v2/shows/{quote(show)}/episodes?limit={PAGE}&offset={offset}"
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                return []
            return resp.json().get("results") or []
        except (requests.RequestException, ValueError):
            return []

    jobs = [(show, off)
            for show, total in per_show.items()
            for off in range(0, min(total, MAX_OFFSET + PAGE), PAGE)]
    print(f"phase 1: {len(jobs)} page requests", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for results in pool.map(fetch_page, jobs):
            for episode in results:
                key = (episode.get("show_alias"), episode.get("episode_alias"))
                if key in wanted:
                    found[key] = row_from(episode)

    def fetch_one(key):
        show, alias = key
        url = f"https://www.nts.live/api/v2/shows/{quote(show)}/episodes/{quote(alias)}"
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                return key, None
            return key, row_from(resp.json())
        except (requests.RequestException, ValueError):
            return key, None

    gaps = [k for k in wanted if k not in found]
    print(f"phase 2: {len(gaps)} episodes past the offset ceiling", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for key, row in pool.map(fetch_one, gaps):
            if row:
                found[key] = row

    rows = sorted(found.values(), key=lambda r: (r["broadcast"], r["show_alias"]), reverse=True)
    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} episodes -> {args.out} ({len(wanted) - len(rows)} unresolved)", file=sys.stderr)


if __name__ == "__main__":
    main()
