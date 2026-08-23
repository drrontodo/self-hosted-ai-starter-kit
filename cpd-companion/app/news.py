"""M3 — Neurology news digest & reading log (Cat 1).

Feed polling (RSS + PubMed E-utilities), PBS schedule monthly diff, Stroke
Foundation living-guidelines diff, the nightly `digest` claude job, and the
weekly reading rollup that turns measured reading time into a draft Cat 1
activity with a generated reading-log evidence document.

All network access goes through _http_get()/_fetch_pbs_items() so tests can
stub it; the poller records per-feed status instead of raising, so one broken
feed never blocks the rest.
"""

import calendar
import hashlib
import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from . import config, db

log = logging.getLogger("cpd.news")

SECTIONS = [
    "Drugs & regulatory AU",
    "Guidelines",
    "Stroke",
    "Epilepsy",
    "MS",
    "Movement disorders",
    "Headache",
    "Neuropathy",
    "General",
]

DIGEST_FLAGS = ("cultural_safety", "ethics")

# Marking an item read stores at most 2 h of reading time; anything above is a
# tab left open, not reading.
READ_SECONDS_CAP = 7200

SUMMARY_MAX_CHARS = 4000
DIGEST_BATCH_LIMIT = 60

USER_AGENT = "CPD-Companion/1.0 (self-hosted CPD tracker)"

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# NCBI asks for <=3 req/s without an API key.
PUBMED_DELAY = 0.34
PUBMED_RELDATE = 7
PUBMED_RETMAX = 50

_PUBMED_FILTER = (
    "(randomized controlled trial[pt] OR practice guideline[pt]"
    " OR guideline[pt] OR systematic review[pt])"
)

# The §4 shortlist from docs/cme-tracker/research/news-sources.md. URLs marked
# unverified there are seeded with a status note (fix them on the Feeds page
# after running scripts/probe_sources.py from the deployment network).
DEFAULT_FEEDS = [
    ("TGA all alerts", "rss", "https://tga.gov.au/feeds/alert.xml",
     "Drugs & regulatory AU", 1, ""),
    ("TGA news", "rss", "https://tga.gov.au/feeds/article/news.xml",
     "Drugs & regulatory AU", 1, ""),
    ("NeurologyLive", "rss", "https://www.neurologylive.com/rss", "General", 1, ""),
    ("The Medical Republic", "rss", "https://www.medicalrepublic.com.au/feed",
     "General", 1, ""),
    ("Neurology (AAN) eTOC", "rss",
     "https://www.neurology.org/action/showFeed?type=etoc&feed=rss&jc=wnl",
     "General", 1, "unverified URL — copy the exact feed from neurology.org/rss"),
    ("JAMA Neurology Online First", "rss",
     "https://jamanetwork.com/rss/site_16/onlineFirst_16.xml",
     "General", 1, "unverified URL — copy the exact feed from jamanetwork.com/pages/rss"),
    ("Lancet Neurology", "rss", "https://www.thelancet.com/rssfeed/laneur_online.xml",
     "General", 1, "unverified URL — copy the exact feed from thelancet.com/content/rss"),
    ("Medscape Neurology", "rss", "https://www.medscape.com/cx/rssfeeds/2698.xml",
     "General", 0, "disabled until the URL is confirmed from the home network"),
    ("PubMed — stroke", "pubmed", f"(stroke) AND {_PUBMED_FILTER}", "Stroke", 1, ""),
    ("PubMed — epilepsy", "pubmed", f"(epilepsy) AND {_PUBMED_FILTER}", "Epilepsy", 1, ""),
    ("PubMed — multiple sclerosis", "pubmed",
     f"(multiple sclerosis) AND {_PUBMED_FILTER}", "MS", 1, ""),
    ("PubMed — movement disorders", "pubmed",
     f"(parkinson disease OR movement disorders) AND {_PUBMED_FILTER}",
     "Movement disorders", 1, ""),
    ("PubMed — headache", "pubmed",
     f"(migraine OR headache disorders) AND {_PUBMED_FILTER}", "Headache", 1, ""),
    ("PubMed — neuropathy", "pubmed",
     f"(peripheral neuropathy OR polyneuropathy) AND {_PUBMED_FILTER}",
     "Neuropathy", 1, ""),
]

STROKE_UPDATES_URL = "https://informme.org.au/guidelines/living-guidelines-updates"


def seed_default_feeds() -> None:
    """Populate the feeds table on first run only — deletions must stick."""
    with db.tx() as conn:
        if conn.execute("SELECT COUNT(*) AS n FROM feeds").fetchone()["n"]:
            return
        conn.executemany(
            "INSERT OR IGNORE INTO feeds (name, kind, url, section, enabled, last_status,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(n, k, u, s, e, st, db.now_iso()) for n, k, u, s, e, st in DEFAULT_FEEDS],
        )


def _http_get(url: str, params: dict | None = None) -> httpx.Response:
    resp = httpx.get(url, params=params, timeout=30,
                     headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    resp.raise_for_status()
    return resp


def safe_err(exc: Exception) -> str:
    """Exception text safe to persist/log: never echo URL query strings, which
    can carry API keys (NCBI, Google Places)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} from {exc.request.url.host}"
    if isinstance(exc, httpx.RequestError):
        return f"{type(exc).__name__} contacting {exc.request.url.host}"
    return re.sub(r"(?i)([?&](?:key|api_key)=)[^&'\"\s]+", r"\1REDACTED", str(exc))


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def _clean_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", _strip_html(text))
    return text[:SUMMARY_MAX_CHARS]


def _insert_item(conn, *, feed_id: int | None, source: str, guid: str, link: str,
                 title: str, summary: str, published_at: str | None,
                 section: str = "") -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO news_items (feed_id, source, guid, link, title, summary,"
        " published_at, fetched_at, section) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (feed_id, source, guid, link, title[:500], summary, published_at,
         db.now_iso(), section),
    )
    return cur.rowcount > 0


def _entry_published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                # feedparser normalises to UTC; date it in the local timezone.
                stamp = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
                return stamp.astimezone(config.TZ).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OverflowError, OSError):
                continue
    return None


def _poll_rss(feed) -> int:
    import feedparser

    body = _http_get(feed["url"]).content
    parsed = feedparser.parse(body)
    if parsed.get("bozo") and not parsed.entries:
        raise ValueError(f"not a parseable feed: {parsed.get('bozo_exception')}")
    new = 0
    with db.tx() as conn:
        for entry in parsed.entries[:100]:
            link = entry.get("link", "") or ""
            guid = entry.get("id") or link
            title = _strip_html(entry.get("title", "")) or "(untitled)"
            if not guid:
                guid = f"{feed['url']}#{hashlib.sha256(title.encode()).hexdigest()[:16]}"
            if _insert_item(
                conn, feed_id=feed["id"], source=feed["name"], guid=guid, link=link,
                title=title, summary=_clean_summary(entry.get("summary", "")),
                published_at=_entry_published(entry), section=feed["section"] or "",
            ):
                new += 1
    return new


def _pubmed_params(extra: dict) -> dict:
    params = dict(extra)
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    return params


def _pubmed_date(article) -> str | None:
    node = article.find(".//Article/Journal/JournalIssue/PubDate")
    if node is None:
        return None
    year = node.findtext("Year")
    if not year:
        medline = node.findtext("MedlineDate") or ""
        match = re.search(r"\d{4}", medline)
        return match.group() if match else None
    months = {m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
    month = months.get((node.findtext("Month") or "")[:3], 1)
    try:
        day = int(node.findtext("Day") or 1)
    except ValueError:
        day = 1
    return f"{int(year):04d}-{month:02d}-{day:02d}"


def _poll_pubmed(feed) -> int:
    search = _http_get(
        f"{EUTILS_BASE}/esearch.fcgi",
        _pubmed_params({
            "db": "pubmed", "term": feed["url"], "reldate": PUBMED_RELDATE,
            "datetype": "edat", "retmode": "json", "retmax": PUBMED_RETMAX,
        }),
    ).json()
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return 0
    time.sleep(PUBMED_DELAY)
    fetched = _http_get(
        f"{EUTILS_BASE}/efetch.fcgi",
        _pubmed_params({
            "db": "pubmed", "id": ",".join(ids), "retmode": "xml", "rettype": "abstract",
        }),
    )
    root = ET.fromstring(fetched.content)
    new = 0
    with db.tx() as conn:
        for article in root.iter("PubmedArticle"):
            pmid = article.findtext(".//MedlineCitation/PMID")
            if not pmid:
                continue
            title = _strip_html("".join(
                article.find(".//Article/ArticleTitle").itertext()
            ) if article.find(".//Article/ArticleTitle") is not None else "")
            abstract = " ".join(
                " ".join(node.itertext()).strip()
                for node in article.findall(".//Abstract/AbstractText")
            )
            journal = article.findtext(".//Article/Journal/Title") or "PubMed"
            if _insert_item(
                conn, feed_id=feed["id"], source=f"{feed['name']} ({journal})",
                guid=f"pubmed:{pmid}", link=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                title=title or "(untitled)", summary=_clean_summary(abstract),
                published_at=_pubmed_date(article), section=feed["section"] or "",
            ):
                new += 1
    return new


def poll_feed(feed) -> int:
    if feed["kind"] == "pubmed":
        return _poll_pubmed(feed)
    return _poll_rss(feed)


def poll_all_feeds() -> dict:
    """Poll every enabled feed; per-feed errors are recorded, never raised."""
    with db.tx() as conn:
        feeds = conn.execute(
            "SELECT * FROM feeds WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    results: dict[str, str] = {}
    total_new = 0
    for i, feed in enumerate(feeds):
        if i and feed["kind"] == "pubmed":
            time.sleep(PUBMED_DELAY)
        try:
            new = poll_feed(feed)
            status = f"ok: {new} new"
            total_new += new
        except Exception as exc:  # noqa: BLE001 - keep polling the other feeds
            status = f"error: {safe_err(exc)[:300]}"
            log.warning("feed %s failed: %s", feed["name"], safe_err(exc))
        results[feed["name"]] = status
        with db.tx() as conn:
            conn.execute(
                "UPDATE feeds SET last_polled_at = ?, last_status = ? WHERE id = ?",
                (db.now_iso(), status, feed["id"]),
            )
    results["_total_new"] = str(total_new)
    return results


# --- PBS Schedule monthly diff -------------------------------------------------

def _latest_snapshot(conn, source: str) -> dict | None:
    row = conn.execute(
        "SELECT content FROM source_snapshots WHERE source = ? ORDER BY id DESC LIMIT 1",
        (source,),
    ).fetchone()
    return json.loads(row["content"]) if row else None


def _save_snapshot(conn, source: str, content: dict) -> None:
    conn.execute(
        "INSERT INTO source_snapshots (source, taken_at, content) VALUES (?, ?, ?)",
        (source, db.now_iso(), json.dumps(content)),
    )
    # Keep the last 14 snapshots per source; diffs only ever use the latest.
    conn.execute(
        "DELETE FROM source_snapshots WHERE source = ? AND id NOT IN"
        " (SELECT id FROM source_snapshots WHERE source = ? ORDER BY id DESC LIMIT 14)",
        (source, source),
    )


def _fetch_pbs_items() -> dict[str, dict]:
    """Current PBS schedule, filtered to the configured ATC prefixes.

    Returns {pbs_code: {"name": ..., "atc": ..., "restriction": ...}}. The API
    base/subscription key are configurable because the public endpoint shape
    should be smoke-tested from the deployment network (see the research doc).
    """
    prefixes = tuple(
        p.strip().upper()
        for p in db.get_setting("pbs_atc_prefixes", "N02C,N03,N04,N07,L04").split(",")
        if p.strip()
    )
    headers = {"User-Agent": USER_AGENT}
    if config.PBS_SUBSCRIPTION_KEY:
        headers["Subscription-Key"] = config.PBS_SUBSCRIPTION_KEY
    items: dict[str, dict] = {}
    url = f"{config.PBS_API_BASE}/items"
    page = 1
    while True:
        resp = httpx.get(url, params={
            "get_latest_schedule_only": "true", "limit": 1000, "page": page,
        }, headers=headers, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        body = resp.json()
        rows = body.get("data", body if isinstance(body, list) else [])
        if not rows:
            break
        for row in rows:
            atc = str(row.get("atc5_code") or row.get("atc_code") or "").upper()
            if prefixes and not atc.startswith(prefixes):
                continue
            code = str(row.get("pbs_code") or row.get("li_item_id") or "")
            if not code:
                continue
            items[code] = {
                "name": str(row.get("drug_name") or row.get("li_drug_name") or ""),
                "brand": str(row.get("brand_name") or ""),
                "atc": atc,
                "restriction": str(row.get("benefit_type_code") or ""),
            }
        meta = body.get("_meta", {})
        if page >= int(meta.get("total_pages", page)):
            break
        page += 1
        time.sleep(0.5)
    return items


def pbs_monthly_diff() -> dict:
    """Diff this month's PBS schedule against the stored snapshot.

    The first run only records the baseline. Later runs turn every new or
    changed neurology-relevant listing into a news item (guid-deduped, so
    re-runs within a month are safe).
    """
    try:
        current = _fetch_pbs_items()
    except Exception as exc:  # noqa: BLE001 - surfaced on the feeds page
        db.set_setting("pbs_last_status", f"error: {safe_err(exc)[:300]}")
        db.set_setting("pbs_last_run", db.now_iso())
        return {"error": safe_err(exc)}
    stamp = datetime.now(config.TZ).strftime("%Y%m")
    new_items = 0
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = _latest_snapshot(conn, "pbs")
        if previous is not None:
            for code, item in current.items():
                old = previous.get(code)
                if old == item:
                    continue
                verb = "changed on" if old else "newly listed on"
                title = f"{item['name'] or code} ({item['brand']}) {verb} the PBS"
                detail = f"ATC {item['atc']}, PBS code {code}."
                if old:
                    detail += f" Previous entry: {json.dumps(old)}. Now: {json.dumps(item)}."
                # The guid carries a content hash so a second distinct change to
                # the same item within a month still lands (identical re-runs
                # still dedupe), and only real inserts are counted.
                content = hashlib.sha256(
                    json.dumps(item, sort_keys=True).encode()).hexdigest()[:10]
                if _insert_item(
                    conn, feed_id=None, source="PBS schedule",
                    guid=f"pbs:{stamp}:{code}:{content}",
                    link=f"https://www.pbs.gov.au/medicine/item/{code}",
                    title=title, summary=detail, published_at=db.today_iso(),
                    section="Drugs & regulatory AU",
                ):
                    new_items += 1
        _save_snapshot(conn, "pbs", current)
    db.set_setting("pbs_last_status",
                   f"ok: {len(current)} tracked items, {new_items} new/changed")
    db.set_setting("pbs_last_run", db.now_iso())
    return {"tracked": len(current), "new_or_changed": new_items,
            "baseline_only": previous is None}


# --- Stroke Foundation living guidelines diff ---------------------------------

def _page_lines(html_text: str) -> list[str]:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html_text)
    lines = []
    for raw in re.split(r"(?i)</p>|<br\s*/?>|</li>|</h[1-6]>|</div>", text):
        line = re.sub(r"\s+", " ", _strip_html(raw))
        if len(line) > 40:  # skip nav crumbs and short boilerplate
            lines.append(line)
    return lines


def stroke_guidelines_diff() -> dict:
    url = db.get_setting("stroke_updates_url", STROKE_UPDATES_URL)
    try:
        page = _http_get(url).text
    except Exception as exc:  # noqa: BLE001 - surfaced on the feeds page
        db.set_setting("stroke_last_status", f"error: {safe_err(exc)[:300]}")
        db.set_setting("stroke_last_run", db.now_iso())
        return {"error": safe_err(exc)}
    lines = _page_lines(page)
    added = 0
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = _latest_snapshot(conn, "stroke_foundation")
        if previous is not None:
            old_lines = set(previous.get("lines", []))
            fresh = [l for l in lines if l not in old_lines]
            if fresh:
                joined = "\n".join(f"- {l}" for l in fresh[:40])
                digest_hash = hashlib.sha256("\n".join(fresh).encode()).hexdigest()[:16]
                if _insert_item(
                    conn, feed_id=None, source="Stroke Foundation living guidelines",
                    guid=f"stroke:{digest_hash}", link=url,
                    title="Living Stroke Guidelines page updated",
                    summary=f"New content on the updates page:\n{joined}"[:SUMMARY_MAX_CHARS],
                    published_at=db.today_iso(), section="Guidelines",
                ):
                    added = 1
        _save_snapshot(conn, "stroke_foundation", {"lines": lines})
    db.set_setting("stroke_last_status",
                   f"ok: {len(lines)} lines, {'update detected' if added else 'no change'}")
    db.set_setting("stroke_last_run", db.now_iso())
    return {"lines": len(lines), "update_item_created": bool(added),
            "baseline_only": previous is None}


# --- Nightly digest job --------------------------------------------------------

def _digest_prompt() -> str:
    return (
        "You are preparing the daily neurology news digest for an RACP CPD tracker.\n"
        "The payload's `items` array holds new items (id, source, title, summary).\n"
        "Return a JSON result with keys:\n"
        "  overview_md: 3-6 bullet markdown overview of what actually matters today\n"
        "  items: array of {id, digest, section, flags} — one entry per input item:\n"
        f"    section: exactly one of {SECTIONS}\n"
        "    digest: 1-3 sentence summary in plain clinical language\n"
        "    flags: subset of [\"cultural_safety\", \"ethics\"] — flag only items that\n"
        "      plausibly qualify for the RACP cultural-safety or ethics mandatory\n"
        "      counters (e.g. Indigenous health, consent, end-of-life, professional\n"
        "      conduct). Most items have no flags.\n"
        "STRICT RULES: summarise only from the provided title/summary — never invent\n"
        "findings, numbers, or conclusions; if a summary is empty, base the digest on\n"
        "the title alone and say so. Keep every provided id; do not add new ids."
    )


def queue_digest_job() -> int | None:
    """Create the nightly `digest` claude job over undigested items (if any)."""
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        pending = conn.execute(
            "SELECT id FROM jobs WHERE kind = 'digest' AND status = 'pending'"
        ).fetchone()
        if pending:
            return None
        rows = conn.execute(
            "SELECT id, source, title, summary, link FROM news_items"
            " WHERE llm_digest IS NULL ORDER BY id DESC LIMIT ?",
            (DIGEST_BATCH_LIMIT,),
        ).fetchall()
        if not rows:
            return None
        payload = {"items": [
            {"id": r["id"], "source": r["source"], "title": r["title"],
             "summary": r["summary"][:1500]}
            for r in rows
        ]}
        cur = conn.execute(
            "INSERT INTO jobs (kind, engine, payload, prompt, created_at)"
            " VALUES ('digest', 'claude', ?, ?, ?)",
            (json.dumps(payload), _digest_prompt(), db.now_iso()),
        )
        return cur.lastrowid


def apply_digest_result(conn, job, result: dict) -> dict:
    """Handle a posted `digest` job result inside the caller's transaction."""
    items = result.get("items")
    if not isinstance(items, list):
        return {"error": "result must include an 'items' array"}
    payload = json.loads(job["payload"] or "{}")
    known_ids = {i["id"] for i in payload.get("items", [])}
    updated = 0
    for entry in items:
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        # ids come from integer primary keys; anything else (lists, strings…)
        # is malformed runner output and is skipped, not a 500.
        if not isinstance(entry_id, int) or entry_id not in known_ids:
            continue
        digest = str(entry.get("digest", "")).strip()
        if not digest:
            continue
        section = entry.get("section")
        if section not in SECTIONS:
            section = "General"
        flags = ",".join(
            f for f in DIGEST_FLAGS
            if isinstance(entry.get("flags"), list) and f in entry["flags"]
        )
        conn.execute(
            "UPDATE news_items SET llm_digest = ?, section = ?, digest_flags = ?"
            " WHERE id = ?",
            (digest[:2000], section, flags, entry_id),
        )
        updated += 1
    overview = str(result.get("overview_md", "")).strip()
    if overview:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('digest_overview_md', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (overview[:8000],))
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('digest_overview_date', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (db.today_iso(),))
    conn.execute(
        "UPDATE jobs SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
        (json.dumps({"updated_items": updated}), db.now_iso(), job["id"]),
    )
    return {"job": job["id"], "status": "done", "updated_items": updated}


# --- Reading log ---------------------------------------------------------------

def mark_read(item_id: int, seconds: int) -> bool:
    seconds = max(0, min(int(seconds), READ_SECONDS_CAP))
    with db.tx() as conn:
        changed = conn.execute(
            "UPDATE news_items SET read_at = ?, read_seconds = read_seconds + ?"
            " WHERE id = ? AND read_at IS NULL",
            (db.now_iso(), seconds, item_id),
        ).rowcount
    return changed > 0


def rollup_reading() -> list[int]:
    """Weekly rollup: read-but-unrolled items -> one draft Cat 1 reading activity
    per ISO week, with a generated reading-log document as evidence. Mirrors the
    honesty model of the sessions rollup: minutes come from the measured
    visibility timer, and the draft still needs dashboard sign-off."""
    created: list[int] = []
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM news_items WHERE read_at IS NOT NULL AND rolled_up = 0"
            " ORDER BY read_at"
        ).fetchall()
        groups: dict[tuple, list] = {}
        for r in rows:
            # Key on the full ISO pair so year-boundary weeks label correctly
            # (e.g. 2025-12-29 belongs to ISO 2026-W01, not "2025 week 1").
            iso = datetime.fromisoformat(r["read_at"]).date().isocalendar()
            groups.setdefault((iso[0], iso[1]), []).append(r)
        for (year, week), items in groups.items():
            minutes = round(sum(i["read_seconds"] for i in items) / 60)
            if minutes <= 0:
                conn.executemany("UPDATE news_items SET rolled_up = 1 WHERE id = ?",
                                 [(i["id"],) for i in items])
                continue
            last_day = max(i["read_at"] for i in items)[:10]
            # Digest cultural-safety/ethics flags carry through to the draft's
            # tags, so confirming the reading feeds the mandatory counters; the
            # human still signs the draft (and can edit tags on the edit page).
            tags = ",".join(sorted({
                f for i in items for f in (i["digest_flags"] or "").split(",")
                if f in config.TAG_OPTIONS
            }))
            now = db.now_iso()
            cur = conn.execute(
                "INSERT INTO activities (date, category, activity_type, title,"
                " description, minutes, source_module, status, tags, created_at)"
                " VALUES (?, 1, 'reading', ?, ?, ?, 'news', 'draft', ?, ?)",
                (
                    last_day,
                    f"Neurology literature & news reading — {year} week {week}",
                    f"{len(items)} digest items read; see the attached reading log.",
                    minutes, tags, now,
                ),
            )
            activity_id = cur.lastrowid
            doc = config.EVIDENCE_DIR / f"reading-log-{year}-W{week:02d}-a{activity_id}.md"
            lines = [
                f"# Reading log — {year} week {week}", "",
                "| Date | Source | Item | Minutes |", "|---|---|---|---|",
            ]
            for i in items:
                item_min = round(i["read_seconds"] / 60, 1)
                title = i["title"].replace("|", "/")
                cell = f"[{title}]({i['link']})" if i["link"] else title
                lines.append(f"| {i['read_at'][:10]} | {i['source'].replace('|', '/')}"
                             f" | {cell} | {item_min} |")
            lines += ["", f"Total: {minutes} minutes across {len(items)} items."]
            db.add_generated_evidence(conn, activity_id, doc,
                                      "\n".join(lines).encode("utf-8"))
            conn.executemany("UPDATE news_items SET rolled_up = 1 WHERE id = ?",
                             [(i["id"],) for i in items])
            created.append(activity_id)
    return created


# --- Digest item flags (the info-sheet action lives in growth.py) --------------

def item_action(item_id: int, action: str) -> bool:
    with db.tx() as conn:
        item = conn.execute("SELECT id FROM news_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            return False
        if action == "opportunity":
            conn.execute(
                "UPDATE news_items SET flagged_opportunity = 1 - flagged_opportunity"
                " WHERE id = ?", (item_id,))
            return True
        if action == "newsletter":
            conn.execute(
                "UPDATE news_items SET flagged_newsletter = 1 - flagged_newsletter"
                " WHERE id = ?", (item_id,))
            return True
    return False
