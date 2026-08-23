# Neurology News Digest — Source Research

> Research compiled 2026-08-23. The research environment's egress proxy blocked direct fetches of publisher domains, so "Confirmed" means the URL is published on the source's own official RSS/documentation page; "pattern/legacy" means it follows the platform's standard scheme and should be smoke-tested with `curl -I <url>` from the deployment network before wiring in.

## 1. Feed URL table

| Source | Coverage | Feed / API URL | Status | Cost / auth |
|---|---|---|---|---|
| **TGA safety alerts** | AU drug/device safety | `https://tga.gov.au/feeds/alert/safety-alerts.xml` | Confirmed (TGA official RSS page) | Free, no auth |
| **TGA all alerts** | Safety + shortages + recalls | `https://tga.gov.au/feeds/alert.xml` | Confirmed | Free |
| **TGA medicine shortages** | AU shortages | `https://tga.gov.au/feeds/alert/medicine-shortage-alerts.xml` | Confirmed | Free |
| **TGA news** | Approvals, regulatory news | `https://tga.gov.au/feeds/article/news.xml` | Confirmed | Free |
| **PubMed saved-search RSS** | Any query (per-subspecialty) | `https://pubmed.ncbi.nlm.nih.gov/rss/search/<hash>/?limit=50` — generated via "Create RSS" on any PubMed search | Confirmed feature (NLM Technical Bulletin) | Free, no auth |
| **PubMed E-utilities** | Same, as JSON/XML API | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=<query>&reldate=7&datetype=edat&retmode=json` | Confirmed, stable NLM API | Free; 3 req/s, 10 req/s with free API key |
| **PBS Schedule Data API** | AU PBS listings, monthly | `https://data.pbs.gov.au` public API (docs at info.data.pbs.gov.au); monthly API CSV files | Confirmed (pbs.gov.au, Dec 2024) | Free, no auth |
| **Neurology (AAN journal)** | General neuro research | Directory: `https://www.neurology.org/rss`; Atypon pattern `https://www.neurology.org/action/showFeed?type=etoc&feed=rss&jc=wnl` | Directory confirmed; exact URL verify | Feed free; full text paywalled |
| **JAMA Neurology** | General neuro research | Directory: `https://jamanetwork.com/pages/rss`; feeds under `https://jamanetwork.com/rss/site_16/...xml` (Online First daily) | Directory confirmed; site number verify | Feed free; paywalled |
| **Lancet Neurology** | Research + policy | Directory: `https://www.thelancet.com/content/rss`; legacy `https://www.thelancet.com/rssfeed/laneur_current.xml`, `.../laneur_online.xml` | Directory confirmed; legacy unverified | Feed free; paywalled |
| **Brain (OUP)** | Research | RSS icons on `https://academic.oup.com/brain`; pattern `https://academic.oup.com/rss/site_<n>/<n>.xml` | Options confirmed; numbers verify | Free feed |
| **Practical Neurology (BMJ)** | Practical/clinical reviews | HighWire pattern: `https://pn.bmj.com/rss/current.xml`, `.../recent.xml` | Pattern only | Free feed |
| **Neurology Today (AAN news)** | Neuro practice news | LWW `journals.lww.com/neurotodayonline` — feed link on journal page | Unverified | Free content |
| **NeurologyLive** | Drug approvals, trials, conference news | `https://www.neurologylive.com/rss` | Reported by directories; unverified | Free |
| **MedPage Today** | US clinical news incl. neuro | `https://www.medpagetoday.com/rss/headlines.xml`; neurology legacy `.../rss/neurology.xml` | Unverified; RSS throttled in recent years | Free headlines; free login |
| **The Medical Republic** | AU medical/practice news | `https://www.medicalrepublic.com.au/feed` (standard WP endpoint) | Pattern, near-certain | Free feed; some free-login |
| **Australian Doctor (AusDoc)** | AU medical news | `https://www.ausdoc.com.au/feed` (WP pattern) | Unverified | Free feed likely; free registration |
| **Medscape Neurology** | News, conference coverage, drug info | Legacy per-specialty feeds `https://www.medscape.com/cx/rssfeeds/<id>.xml` (neurology historically `2698.xml`) | Unverified — test from home network | Feed free; full articles need free login |

## 2. Source notes

### Medscape (credentials available)
- Legacy per-specialty RSS still listed by directories under `medscape.com/cx/rssfeeds/`. Headlines/summaries readable without login; full articles need the free account.
- **Recommendation:** poll RSS for headlines only — do not automate login. No public API, ToS prohibit scraping, aggressive bot protection, and session-replay automation breaks on auth rotation. RSS headline + link into the digest, click through manually, is the sustainable pattern. If legacy feed IDs are dead, a self-hosted RSS-Bridge container can synthesize a feed from the neurology section page.

### PubMed / NCBI E-utilities — the workhorse
1. **Per-search RSS:** run each subspecialty search once in the PubMed UI (e.g. `(epilepsy) AND (randomized controlled trial[pt])`, similarly for MS, stroke, movement disorders, headache, peripheral neuropathy), click **Create RSS**, get a permanent feed URL. Only new items appear.
2. **E-utilities API:** `esearch` with `reldate=7` returns PMIDs from the last 7 days; `efetch` with `rettype=abstract` returns abstracts for LLM summarisation. 3 req/s without key, 10/s with free NCBI API key.
- Useful filters: `randomized controlled trial[pt]`, `guideline[pt]`, `systematic review[pt]`, `"Lancet Neurol"[jour]`.

### Journals and news outlets
- **Neurology (AAN)**: the `neurology.org/rss` directory covers Neurology + Neurology Clinical Practice, Neuroimmunology & Neuroinflammation, Genetics — AAN practice guidelines are published in Neurology, so this feed doubles as the AAN guideline alert.
- **JAMA Neurology:** pick "Online First" (daily) over current-issue (monthly).
- **MedPage Today** has deprioritized RSS; treat as best-effort.

### Australian drug/regulatory
- **TGA:** first-class documented RSS (full list: https://www.tga.gov.au/news/subscribe-updates/rss-feeds) — strongest AU source. Safety alerts + news + shortages.
- **PBS:** no news RSS, but the **PBS Schedule Data API** (public, free, updated 1st of each month; legacy XML retires 1 May 2026) is ideal for a monthly job: pull schedule, diff against last month's snapshot, report new/changed neurology items (ATC N03/N04/N06/N07, MS DMTs, CGRP agents, etc.).
- **Australian Prescriber:** now free under Therapeutic Guidelines at `australianprescriber.tg.org.au`; email alerts confirmed, no RSS confirmed; 6 issues/yr so a quarterly scrape of the articles index is fine.
- **NPS MedicineWise: defunct** (closed Jan 2023; RADAR gone). Australian Prescriber is the successor.

### Guidelines
- **NICE:** the supported route is the **NICE Syndication API** — free but requires a licence application and API key (reviewed monthly).
- **AAN:** no guideline feed; caught via the Neurology journal RSS, plus optional monthly scrape of `aan.com/practice/guidelines`.
- **Stroke Foundation (AU):** Living Stroke Guidelines updates page at `https://informme.org.au/guidelines/living-guidelines-updates` — no RSS; roughly quarterly batches; monthly scrape-and-diff is trivial and reliable.

## 3. Authentication / automation difficulty

| Source | Auth needed? | Automation difficulty |
|---|---|---|
| Medscape full articles | Free login | High — bot protection, ToS; use RSS headlines only |
| Australian Doctor full articles | Free registration | Medium — feed headlines fine |
| NICE Syndication API | Free API key after application | Low once key issued; application takes weeks |
| Journal full texts | Subscription | Feeds + abstracts free; link out, don't automate paywalls |
| Everything else | None | Low — plain RSS/JSON |

## 4. Recommended shortlist (8 feeds + 2 API jobs)

1. **TGA all alerts** — `https://tga.gov.au/feeds/alert.xml` (daily)
2. **TGA news** — `https://tga.gov.au/feeds/article/news.xml` (daily)
3. **PubMed RSS #1** — stroke + epilepsy RCTs/guidelines (daily)
4. **PubMed RSS #2** — MS, movement disorders, headache, neuropathy RCTs/guidelines (daily; or one per subspecialty)
5. **Neurology (AAN) eTOC** — from `neurology.org/rss` (weekly; catches AAN guidelines)
6. **JAMA Neurology Online First** — from `jamanetwork.com/pages/rss` (daily)
7. **Lancet Neurology Online First** — from `thelancet.com/content/rss` (weekly)
8. **NeurologyLive** — `https://www.neurologylive.com/rss` (daily), with Medscape neurology RSS as an addition once its URL is confirmed from the home network
9. *(API job)* **PBS Schedule API monthly diff** — 1st of each month, diff, surface new neuro listings
10. *(API job / scrape)* **Stroke Foundation living guidelines updates page** — monthly scrape-and-diff; optionally add The Medical Republic `/feed` for AU practice news

## 5. Could not verify (flagged)
- Exact XML URLs for: Medscape neurology, Neurology.org eTOC, JAMA Neurology site number, Lancet legacy paths, Brain OUP site numbers, Practical Neurology, Neurology Today, MedPage neurology, Medical Republic/AusDoc WP feeds — each has an authoritative feed-directory page listed above to copy from (minutes each from a normal network).
- Whether MedPage Today's specialty feeds are still maintained.
- Whether Australian Prescriber/TG exposes any RSS (email alerts are the only confirmed channel).
- PBS has no confirmed news RSS — email subscription and the Schedule API are the channels.
