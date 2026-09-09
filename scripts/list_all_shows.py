#!/usr/bin/env python3
"""
Build a CSV of every NTS show: name, artist, location, link.

Show slugs come from the sitemap (the show-list API is capped at offset 1000,
see list_all_episodes.py); each slug is then resolved via /api/v2/shows/<slug>.

Location is really an episode-level field - a show's own location_long is blank
for 149 shows and reflects a single city for shows that travel - so when the
harvest_episodes.py output is available it is used to derive the show's primary
location (most frequent across its episodes) and the full set it broadcast from.

NTS has no artist/host field. The host, when named at all, lives in the show
name as "Show w/ Host", "Show with Host" or "Host presents Show", so "artist"
is parsed from there; it is blank for the many shows named after their host
or after a theme, which are indistinguishable from each other.

Usage:
    python scripts/list_all_shows.py [output.csv] [--workers N] [--episodes CSV]
"""

import argparse
import csv
import gzip
import io
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

SITEMAP_INDEX = "https://www.nts.live/sitemap.xml.gz"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
SHOW_RE = re.compile(r"^https://www\.nts\.live/shows/([^/?#]+)(?:/episodes/[^/?#]+)?$")
# "with" only in lowercase: "Be With Records" is a label name, not a host credit.
HOST_SUFFIX_RE = re.compile(r"\s+(?:[wW]/|with)\s+(.+)$")
HOST_PREFIX_RE = re.compile(r"^(.+?)\s+presents?\b", re.IGNORECASE)

FIELDS = ["name", "artist", "location", "all_locations", "episodes", "url"]

session = requests.Session()
session.headers.update(HEADERS)


def fetch_locs(url: str):
    resp = session.get(url, timeout=60)
    resp.raise_for_status()
    raw = resp.content
    # NTS serves .xml.gz with Content-Encoding: gzip, so requests may have already decoded it.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return LOC_RE.findall(raw.decode("utf-8"))


def show_slugs():
    slugs = set()
    for sitemap_url in fetch_locs(SITEMAP_INDEX):
        for loc in fetch_locs(sitemap_url):
            match = SHOW_RE.match(loc)
            if match:
                slugs.add(match.group(1))
    return sorted(slugs)


def episode_locations(path):
    """slug -> Counter of the locations that show's episodes broadcast from."""
    per_show = defaultdict(Counter)
    try:
        fh = open(path)
    except OSError:
        return {}
    with fh:
        for row in csv.DictReader(fh):
            if row.get("location"):
                per_show[row["show_alias"]][row["location"]] += 1
    return per_show


def fetch_show(slug: str):
    try:
        resp = session.get(f"https://www.nts.live/api/v2/shows/{slug}", timeout=30)
        if resp.status_code != 200:
            return None
        show = resp.json()
    except (requests.RequestException, ValueError):
        return None

    name = show.get("name") or ""
    host = HOST_SUFFIX_RE.search(name) or HOST_PREFIX_RE.search(name)
    return {
        "slug": slug,
        "name": name,
        "artist": host.group(1).strip(" :-") if host else "",
        "show_location": show.get("location_long") or show.get("location_short") or "",
        "url": f"https://www.nts.live/shows/{slug}",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", nargs="?", default=".scratch/nts_shows.csv")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--episodes", default=".scratch/nts_episodes_full.csv")
    args = parser.parse_args()

    per_show = episode_locations(args.episodes)
    print(f"{len(per_show)} shows with episode locations", file=sys.stderr)

    slugs = show_slugs()
    print(f"{len(slugs)} show slugs from sitemap", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        shows = list(pool.map(fetch_show, slugs))

    missing = sum(1 for s in shows if s is None)
    rows = []
    for show in filter(None, shows):
        counts = per_show.get(show["slug"], Counter())
        ranked = [loc for loc, _ in counts.most_common()]
        rows.append({
            "name": show["name"],
            "artist": show["artist"],
            "location": ranked[0] if ranked else show["show_location"],
            "all_locations": "; ".join(ranked),
            "episodes": sum(counts.values()),
            "url": show["url"],
        })
    rows.sort(key=lambda r: r["name"].lower())

    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} shows -> {args.out} ({missing} slugs unresolved)", file=sys.stderr)


if __name__ == "__main__":
    main()
