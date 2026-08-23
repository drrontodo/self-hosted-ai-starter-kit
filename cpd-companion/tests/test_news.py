"""M3 news digest & reading log tests. Network access is stubbed at the
news._http_get / news._fetch_pbs_items chokepoints."""

import json
import os

import pytest

from tests.test_app import KEY, client, login  # noqa: F401 - reuse env setup + fixture
from app import db, news

RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>TGA test</title>
<item><guid>tga-1</guid><title>Safety alert: drug X &amp; batch recall</title>
<link>https://tga.gov.au/alert/1</link>
<description><![CDATA[<p>Recall of <b>drug X</b> 50mg tablets.</p>]]></description>
<pubDate>Mon, 18 Aug 2026 03:00:00 GMT</pubDate></item>
<item><guid>tga-2</guid><title>New listing</title>
<link>https://tga.gov.au/alert/2</link><description>Second item</description></item>
</channel></rss>"""

ESEARCH_BODY = {"esearchresult": {"count": "1", "idlist": ["12345678"]}}

EFETCH_BODY = b"""<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID>
<Article><Journal><Title>Lancet Neurology</Title>
<JournalIssue><PubDate><Year>2026</Year><Month>Aug</Month><Day>15</Day></PubDate></JournalIssue></Journal>
<ArticleTitle>RCT of thing vs placebo in epilepsy</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Seizures are bad.</AbstractText>
<AbstractText Label="RESULTS">Thing reduced seizures by 30%.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""


class FakeResponse:
    def __init__(self, content=b"", json_data=None, text=None):
        self.content = content
        self._json = json_data
        self.text = text if text is not None else content.decode("utf-8", "replace")

    def json(self):
        return self._json


def _feed_row(conn_query_kind, url_substr=None):
    with db.tx() as conn:
        query = "SELECT * FROM feeds WHERE kind = ?"
        params = [conn_query_kind]
        if url_substr:
            query += " AND url LIKE ?"
            params.append(f"%{url_substr}%")
        return conn.execute(query + " ORDER BY id LIMIT 1", params).fetchone()


def test_default_feeds_seeded_once(client):
    with db.tx() as conn:
        n1 = conn.execute("SELECT COUNT(*) AS n FROM feeds").fetchone()["n"]
    assert n1 == len(news.DEFAULT_FEEDS)
    # deleting a feed sticks across restarts (seed only fills an empty table)
    with db.tx() as conn:
        conn.execute("DELETE FROM feeds WHERE name = 'Medscape Neurology'")
    news.seed_default_feeds()
    with db.tx() as conn:
        n2 = conn.execute("SELECT COUNT(*) AS n FROM feeds").fetchone()["n"]
    assert n2 == n1 - 1
    # restore for other tests
    with db.tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO feeds (name, kind, url, section, enabled, created_at)"
            " VALUES ('Medscape Neurology', 'rss', 'https://www.medscape.com/cx/rssfeeds/2698.xml',"
            " 'General', 0, ?)", (db.now_iso(),))


def test_rss_poll_and_dedupe(client, monkeypatch):
    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(RSS_BODY))
    feed = _feed_row("rss", "tga.gov.au/feeds/alert.xml")
    assert news.poll_feed(feed) == 2
    assert news.poll_feed(feed) == 0  # guid dedupe
    with db.tx() as conn:
        item = conn.execute("SELECT * FROM news_items WHERE guid = 'tga-1'").fetchone()
    assert item["title"] == "Safety alert: drug X & batch recall"
    assert "<p>" not in item["summary"] and "drug X" in item["summary"]
    assert item["published_at"] == "2026-08-18"
    assert item["section"] == "Drugs & regulatory AU"


def test_pubmed_poll(client, monkeypatch):
    def fake_get(url, params=None):
        if "esearch" in url:
            assert params["term"].startswith("(epilepsy)")
            return FakeResponse(json_data=ESEARCH_BODY)
        assert "efetch" in url
        return FakeResponse(EFETCH_BODY)

    monkeypatch.setattr(news, "_http_get", fake_get)
    monkeypatch.setattr(news, "PUBMED_DELAY", 0)
    feed = _feed_row("pubmed", "epilepsy")
    assert news.poll_feed(feed) == 1
    assert news.poll_feed(feed) == 0
    with db.tx() as conn:
        item = conn.execute("SELECT * FROM news_items WHERE guid = 'pubmed:12345678'").fetchone()
    assert item["title"] == "RCT of thing vs placebo in epilepsy"
    assert "reduced seizures by 30%" in item["summary"]
    assert item["link"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert item["published_at"] == "2026-08-15"
    assert item["section"] == "Epilepsy"


def test_poll_all_records_errors_and_continues(client, monkeypatch):
    def fake_get(url, params=None):
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": []}})
        if "tga.gov.au" in url:
            return FakeResponse(RSS_BODY)
        raise RuntimeError("connection refused")

    monkeypatch.setattr(news, "_http_get", fake_get)
    monkeypatch.setattr(news, "PUBMED_DELAY", 0)
    results = news.poll_all_feeds()
    assert results["TGA all alerts"].startswith("ok:")
    assert results["NeurologyLive"].startswith("error: connection refused")
    with db.tx() as conn:
        row = conn.execute("SELECT last_status FROM feeds WHERE name = 'NeurologyLive'").fetchone()
    assert row["last_status"].startswith("error:")


def test_digest_job_lifecycle(client, monkeypatch):
    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(RSS_BODY))
    feed = _feed_row("rss", "tga.gov.au/feeds/alert.xml")
    news.poll_feed(feed)

    job_id = news.queue_digest_job()
    assert job_id is not None
    assert news.queue_digest_job() is None  # one pending digest job at a time

    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    job = next(j for j in jobs if j["id"] == job_id)
    assert job["kind"] == "digest"
    ids = [i["id"] for i in job["payload"]["items"]]
    assert len(ids) >= 2
    assert "never invent" in job["prompt"]

    result = {
        "overview_md": "- drug X recalled",
        "items": [
            {"id": ids[0], "digest": "Drug X recalled over impurity.",
             "section": "Drugs & regulatory AU", "flags": []},
            {"id": ids[1], "digest": "Consent guidance updated.",
             "section": "NotASection", "flags": ["ethics", "bogus_flag"]},
            {"id": 999999, "digest": "Injected item", "section": "General", "flags": []},
        ],
    }
    r = client.post(f"/api/jobs/{job_id}/result", headers=KEY, json=result)
    assert r.status_code == 200
    assert r.json()["updated_items"] == 2

    with db.tx() as conn:
        first = conn.execute("SELECT * FROM news_items WHERE id = ?", (ids[0],)).fetchone()
        second = conn.execute("SELECT * FROM news_items WHERE id = ?", (ids[1],)).fetchone()
    assert first["llm_digest"] == "Drug X recalled over impurity."
    assert second["section"] == "General"       # invalid section coerced
    assert second["digest_flags"] == "ethics"   # bogus flag dropped
    assert db.get_setting("digest_overview_md") == "- drug X recalled"

    # double-post rejected
    assert client.post(f"/api/jobs/{job_id}/result", headers=KEY, json=result).status_code == 422


def test_digest_result_requires_items_array(client, monkeypatch):
    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(RSS_BODY))
    news.poll_feed(_feed_row("rss", "tga.gov.au/feeds/alert.xml"))
    job_id = news.queue_digest_job()
    r = client.post(f"/api/jobs/{job_id}/result", headers=KEY, json={"overview_md": "x"})
    assert r.status_code == 422
    # job stays pending after the bad post
    jobs = client.get("/api/jobs", headers=KEY, params={"engine": "claude"}).json()
    assert any(j["id"] == job_id for j in jobs)

    # malformed ids (lists, strings, unknowns) are skipped, not a 500
    r = client.post(f"/api/jobs/{job_id}/result", headers=KEY, json={
        "items": [{"id": [1], "digest": "x"}, {"id": "1", "digest": "x"},
                  {"id": None, "digest": "x"}, "not-a-dict"],
    })
    assert r.status_code == 200
    assert r.json()["updated_items"] == 0


def test_mark_read_and_reading_rollup(client, monkeypatch):
    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(RSS_BODY))
    news.poll_feed(_feed_row("rss", "tga.gov.au/feeds/alert.xml"))
    login(client)
    with db.tx() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM news_items WHERE read_at IS NULL ORDER BY id LIMIT 2")]

    r = client.post(f"/digest/{ids[0]}/read", data={"seconds": "300"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.post(f"/digest/{ids[1]}/read", data={"seconds": "9999999"}, follow_redirects=False)
    assert r.status_code == 303
    with db.tx() as conn:
        capped = conn.execute("SELECT read_seconds FROM news_items WHERE id = ?",
                              (ids[1],)).fetchone()["read_seconds"]
    assert capped == news.READ_SECONDS_CAP

    created = news.rollup_reading()
    assert len(created) == 1
    drafts = client.get("/api/activities", headers=KEY, params={"status": "draft"}).json()
    draft = next(a for a in drafts if a["id"] == created[0])
    assert draft["category"] == 1
    assert draft["activity_type"] == "reading"
    assert draft["source_module"] == "news"
    assert draft["minutes"] == round((300 + news.READ_SECONDS_CAP) / 60)

    # evidence reading log exists and lists both items
    data_dir = os.environ["CPD_DATA_DIR"]
    logs = [f for f in os.listdir(os.path.join(data_dir, "evidence"))
            if f.startswith("reading-log-")]
    assert logs
    # rollup is idempotent
    assert news.rollup_reading() == []


def test_pbs_diff_baseline_then_changes(client, monkeypatch):
    first = {"1234B": {"name": "erenumab", "brand": "Aimovig", "atc": "N02CD01", "restriction": "A"}}
    second = {
        "1234B": {"name": "erenumab", "brand": "Aimovig", "atc": "N02CD01", "restriction": "U"},
        "5678C": {"name": "newdrugumab", "brand": "Newbrand", "atc": "N07XX99", "restriction": "A"},
    }
    monkeypatch.setattr(news, "_fetch_pbs_items", lambda: first)
    out = news.pbs_monthly_diff()
    assert out["baseline_only"] is True and out["new_or_changed"] == 0

    monkeypatch.setattr(news, "_fetch_pbs_items", lambda: second)
    out = news.pbs_monthly_diff()
    assert out["new_or_changed"] == 2
    with db.tx() as conn:
        items = conn.execute(
            "SELECT * FROM news_items WHERE source = 'PBS schedule' ORDER BY id").fetchall()
    titles = [i["title"] for i in items]
    assert any("changed on the PBS" in t for t in titles)
    assert any("newly listed on the PBS" in t for t in titles)
    assert all(i["section"] == "Drugs & regulatory AU" for i in items)
    # re-run within the month: guid dedupe, no duplicates, honest count
    out = news.pbs_monthly_diff()
    assert out["new_or_changed"] == 0
    with db.tx() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM news_items WHERE source = 'PBS schedule'"
                         ).fetchone()["n"]
    assert n == 2
    assert db.get_setting("pbs_last_status").startswith("ok:")

    # a SECOND distinct change to the same item within the month still lands
    third = dict(second)
    third["1234B"] = dict(second["1234B"], restriction="R")
    monkeypatch.setattr(news, "_fetch_pbs_items", lambda: third)
    out = news.pbs_monthly_diff()
    assert out["new_or_changed"] == 1
    with db.tx() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM news_items WHERE source = 'PBS schedule'"
                         ).fetchone()["n"]
    assert n == 3


def test_pbs_fetch_failure_recorded_not_raised(client, monkeypatch):
    def boom():
        raise RuntimeError("api moved")
    monkeypatch.setattr(news, "_fetch_pbs_items", boom)
    out = news.pbs_monthly_diff()
    assert "error" in out
    assert db.get_setting("pbs_last_status").startswith("error: api moved")


def test_stroke_diff(client, monkeypatch):
    page1 = ("<html><body><p>The Living Stroke Guidelines were updated in June 2026 "
             "with new thrombectomy recommendations for large-core infarcts.</p></body></html>")
    page2 = page1.replace("</body>", (
        "<p>August 2026 update: recommendations on tenecteplase dosing in acute "
        "ischaemic stroke were revised following the TASTE-2 trial results.</p></body>"))

    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(text=page1))
    out = news.stroke_guidelines_diff()
    assert out["baseline_only"] is True and out["update_item_created"] is False

    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(text=page2))
    out = news.stroke_guidelines_diff()
    assert out["update_item_created"] is True
    with db.tx() as conn:
        item = conn.execute(
            "SELECT * FROM news_items WHERE source = 'Stroke Foundation living guidelines'"
            " ORDER BY id DESC LIMIT 1").fetchone()
    assert item["section"] == "Guidelines"
    assert "tenecteplase" in item["summary"]
    # unchanged page -> no new item
    before = item["id"]
    out = news.stroke_guidelines_diff()
    assert out["update_item_created"] is False


def test_item_actions(client, monkeypatch):
    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(RSS_BODY))
    news.poll_feed(_feed_row("rss", "tga.gov.au/feeds/alert.xml"))
    login(client)
    with db.tx() as conn:
        item_id = conn.execute("SELECT id FROM news_items WHERE guid = 'tga-1'").fetchone()["id"]

    r = client.post(f"/digest/{item_id}/action/info_sheet", follow_redirects=False)
    assert r.status_code == 303
    client.post(f"/digest/{item_id}/action/info_sheet", follow_redirects=False)  # idempotent
    with db.tx() as conn:
        outputs = conn.execute(
            "SELECT * FROM practice_outputs WHERE source_kind = 'news_item'"
            " AND source_id = ?", (item_id,)).fetchall()
    assert len(outputs) == 1
    assert outputs[0]["kind"] == "info_sheet" and outputs[0]["status"] == "idea"

    client.post(f"/digest/{item_id}/action/opportunity", follow_redirects=False)
    client.post(f"/digest/{item_id}/action/newsletter", follow_redirects=False)
    with db.tx() as conn:
        item = conn.execute("SELECT * FROM news_items WHERE id = ?", (item_id,)).fetchone()
    assert item["flagged_opportunity"] == 1 and item["flagged_newsletter"] == 1
    # toggling off works
    client.post(f"/digest/{item_id}/action/opportunity", follow_redirects=False)
    with db.tx() as conn:
        item = conn.execute("SELECT * FROM news_items WHERE id = ?", (item_id,)).fetchone()
    assert item["flagged_opportunity"] == 0


def test_digest_page_renders(client, monkeypatch):
    monkeypatch.setattr(news, "_http_get", lambda url, params=None: FakeResponse(RSS_BODY))
    news.poll_feed(_feed_row("rss", "tga.gov.au/feeds/alert.xml"))
    login(client)
    page = client.get("/digest").text
    assert "Safety alert: drug X" in page
    assert "Mark read" in page
    assert "Draft patient info sheet" in page
    page = client.get("/feeds").text
    assert "TGA all alerts" in page
    assert "PBS schedule monthly diff" in page


def test_feeds_page_management(client):
    login(client)
    r = client.post("/feeds/add", data={
        "name": "Test feed", "kind": "rss", "url": "https://example.com/feed.xml",
        "section": "Guidelines"}, follow_redirects=False)
    assert r.status_code == 303
    with db.tx() as conn:
        feed = conn.execute("SELECT * FROM feeds WHERE name = 'Test feed'").fetchone()
    assert feed is not None and feed["enabled"] == 1 and feed["section"] == "Guidelines"

    client.post(f"/feeds/{feed['id']}/toggle", follow_redirects=False)
    with db.tx() as conn:
        assert conn.execute("SELECT enabled FROM feeds WHERE id = ?",
                            (feed["id"],)).fetchone()["enabled"] == 0
    client.post(f"/feeds/{feed['id']}/delete", follow_redirects=False)
    with db.tx() as conn:
        assert conn.execute("SELECT * FROM feeds WHERE id = ?", (feed["id"],)).fetchone() is None
