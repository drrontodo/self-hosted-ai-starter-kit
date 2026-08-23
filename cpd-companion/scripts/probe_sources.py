#!/usr/bin/env python3
"""Verify the news-source shortlist from the machine that will actually poll it.

Run on the server (needs only the Python stdlib):

    python scripts/probe_sources.py

Optionally set GOOGLE_PLACES_API_KEY and EAST_NEURO_PLACE_ID in the environment
to also test the Google reviews call end-to-end.
"""

import json
import os
import urllib.error
import urllib.request

FEEDS = [
    ("TGA all alerts", "https://tga.gov.au/feeds/alert.xml"),
    ("TGA news", "https://tga.gov.au/feeds/article/news.xml"),
    ("TGA medicine shortages", "https://tga.gov.au/feeds/alert/medicine-shortage-alerts.xml"),
    ("NeurologyLive", "https://www.neurologylive.com/rss"),
    ("Medscape neurology (legacy)", "https://www.medscape.com/cx/rssfeeds/2698.xml"),
    ("The Medical Republic", "https://www.medicalrepublic.com.au/feed"),
    ("Practical Neurology current", "https://pn.bmj.com/rss/current.xml"),
    ("Lancet Neurology (legacy)", "https://www.thelancet.com/rssfeed/laneur_online.xml"),
    # Journal feed directories — open in a browser and copy exact URLs from these pages:
    #   https://www.neurology.org/rss
    #   https://jamanetwork.com/pages/rss
    #   https://www.thelancet.com/content/rss
]

APIS = [
    (
        "PubMed E-utilities (epilepsy RCTs, last 7 days)",
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        "?db=pubmed&term=epilepsy+AND+randomized+controlled+trial%5Bpt%5D"
        "&reldate=7&datetype=edat&retmode=json&retmax=3",
    ),
]

UA = {"User-Agent": "Mozilla/5.0 (CPD-Companion probe)"}


def fetch(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.status, resp.read(200_000)


def main() -> None:
    print("== RSS feeds ==")
    for name, url in FEEDS:
        try:
            status, body = fetch(url)
            head = body[:500].lower()
            if b"<rss" in head or b"<feed" in head or b"<?xml" in head:
                items = body.count(b"<item>") + body.count(b"<entry>")
                print(f"  OK    {name}: HTTP {status}, {items} items — {url}")
            else:
                print(f"  WARN  {name}: HTTP {status} but not XML (got {body[:60]!r}) — {url}")
        except (urllib.error.URLError, OSError) as e:
            print(f"  FAIL  {name}: {e} — {url}")

    print("\n== APIs ==")
    for name, url in APIS:
        try:
            status, body = fetch(url)
            data = json.loads(body)
            count = data.get("esearchresult", {}).get("count", "?")
            print(f"  OK    {name}: HTTP {status}, {count} results in window")
        except Exception as e:  # noqa: BLE001 - probe script, report anything
            print(f"  FAIL  {name}: {e}")

    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    place = os.environ.get("EAST_NEURO_PLACE_ID")
    print("\n== Google Places (reviews) ==")
    if not key or not place:
        print("  SKIP  set GOOGLE_PLACES_API_KEY and EAST_NEURO_PLACE_ID to test")
        return
    url = (
        "https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place}&fields=name,rating,user_ratings_total,reviews&key={key}"
    )
    try:
        _, body = fetch(url)
        data = json.loads(body)
        if data.get("status") == "OK":
            r = data["result"]
            print(f"  OK    {r.get('name')}: rating {r.get('rating')}, "
                  f"{r.get('user_ratings_total')} total ratings, "
                  f"{len(r.get('reviews', []))} reviews returned")
        else:
            print(f"  FAIL  status={data.get('status')} message={data.get('error_message')}")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {e}")


if __name__ == "__main__":
    main()
