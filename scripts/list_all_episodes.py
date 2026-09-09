#!/usr/bin/env python3
"""
Enumerate every NTS episode URL.

/latest is backed by GET /api/v2/search/episodes?offset=N&limit=12, which
refuses offset > 240 and silently clamps limit > 60 back to 12 - a fixed
300-episode window over an archive of ~89.6k. /api/v2/shows and
/api/v2/shows/<slug>/episodes are capped at offset 1000 the same way. The
sitemap is the only source that enumerates every episode.

Usage:
    python scripts/list_all_episodes.py [output.csv]
"""

import csv
import gzip
import io
import re
import sys
from urllib.parse import unquote

import requests

SITEMAP_INDEX = "https://www.nts.live/sitemap.xml.gz"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
EPISODE_RE = re.compile(r"^https://www\.nts\.live/shows/([^/]+)/episodes/([^/?#]+)$")


def fetch_locs(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    raw = resp.content
    # NTS serves .xml.gz with Content-Encoding: gzip, so requests may have already decoded it.
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    return LOC_RE.findall(raw.decode("utf-8"))


def all_episodes():
    seen = set()
    for sitemap_url in fetch_locs(SITEMAP_INDEX):
        for loc in fetch_locs(sitemap_url):
            match = EPISODE_RE.match(loc)
            if match and loc not in seen:
                seen.add(loc)
                # the sitemap percent-encodes non-ASCII aliases; the API reports them decoded
                yield loc, unquote(match.group(1)), unquote(match.group(2))


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "nts_episodes.csv"
    with open(out_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["url", "show_alias", "episode_alias"])
        count = 0
        for row in all_episodes():
            writer.writerow(row)
            count += 1
    print(f"{count} episodes -> {out_path}")


if __name__ == "__main__":
    main()
