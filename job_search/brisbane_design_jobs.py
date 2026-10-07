"""
Brisbane Design Jobs - live job search
======================================

Pulls live listings for building design, drafting, Archicad / BIM,
drafting & design management and product development roles in Brisbane
and South East Queensland into one ranked, de-duplicated table.

  * Ranks every ad by how well it fits a building designer / drafter
    (title match, Archicad / residential context, location, recency).
  * Flags ads that are NEW since your last search.
  * Opens the same search on SEEK, Indeed, LinkedIn and Google Jobs, plus
    SEEK's architectural drafting category, in one click (no setup needed).
  * Exports to CSV (Excel) or a standalone HTML report.

Live listings come from two job-search APIs with free keys:
  - Adzuna  https://developer.adzuna.com/   (app_id + app_key)
  - Jooble  https://jooble.org/api/about     (API key)
Add them under "API keys". Without keys the "Open board searches" button
still works.

Run: open in Python IDLE and press F5   (or: python brisbane_design_jobs.py)
Headless / scheduled:
    python brisbane_design_jobs.py --cli --days 7 --csv jobs.csv
    python brisbane_design_jobs.py --cli --locations Brisbane "Gold Coast"
Standard library only (Python 3.8+). No pip installs needed.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

APP_NAME = "Brisbane Design Jobs"
APP_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
CONFIG_PATH = os.path.join(APP_DIR, "brisbane_jobs_config.json")
SEEN_PATH = os.path.join(APP_DIR, "brisbane_jobs_seen.json")
USER_AGENT = "BrisbaneDesignJobs/1.0 (+personal job search tool)"


# =====================================================================
# What to search for
# =====================================================================
# Each group is a family of job titles. "default" groups are ticked on
# first launch. Terms are searched as written (multi-word terms match all
# of their words).
ROLE_GROUPS: List[dict] = [
    {
        "name": "Building design",
        "default": True,
        "terms": [
            "building designer",
            "residential building designer",
            "home designer",
            "residential designer",
            "architectural designer",
        ],
    },
    {
        "name": "Drafting",
        "default": True,
        "terms": [
            "draftsperson",
            "drafter",
            "draftsman",
            "architectural draftsperson",
            "architectural drafter",
            "residential draftsperson",
            "senior draftsperson",
            "building drafter",
            "documentation drafter",
        ],
    },
    {
        "name": "Archicad & BIM",
        "default": True,
        "terms": [
            "archicad",
            "revit",
            "BIM modeller",
            "BIM coordinator",
            "architectural technician",
            "architectural documenter",
        ],
    },
    {
        "name": "Drafting & design management",
        "default": True,
        "terms": [
            "drafting manager",
            "drafting team leader",
            "design manager",
            "design coordinator",
            "design and documentation manager",
            "head of design",
            "studio manager",
            "BIM manager",
        ],
    },
    {
        "name": "Product development",
        "default": True,
        "terms": [
            "product development manager",
            "product design manager",
            "product development coordinator",
            "product manager homes",
            "house design range",
        ],
    },
    {
        "name": "Adjacent roles",
        "default": False,
        "terms": [
            "residential estimator",
            "contracts administrator residential",
            "pre-construction coordinator",
            "pre-start consultant",
            "new home sales consultant",
            "energy assessor",
            "building certifier cadet",
            "CAD manager",
        ],
    },
]

DEFAULT_EXCLUDE = ["civil", "mechanical", "electrical", "piping", "mining", "hydraulic"]

# Location presets. "where" is what the APIs and boards understand.
LOCATIONS: Dict[str, dict] = {
    "Brisbane": {"where": "Brisbane", "seek": "All Brisbane QLD", "label": "Brisbane QLD"},
    "Gold Coast": {"where": "Gold Coast", "seek": "All Gold Coast QLD", "label": "Gold Coast QLD"},
    "Sunshine Coast": {"where": "Sunshine Coast", "seek": "Sunshine Coast QLD", "label": "Sunshine Coast QLD"},
    "Toowoomba": {"where": "Toowoomba", "seek": "Toowoomba & Darling Downs QLD", "label": "Toowoomba QLD"},
}

# Places counted as "in South East Queensland" when ranking.
SEQ_PLACES = [
    "brisbane", "qld", "queensland", "gold coast", "sunshine coast", "ipswich", "logan",
    "moreton bay", "redland", "redcliffe", "north lakes", "caboolture", "springfield",
    "toowoomba", "southport", "robina", "burleigh", "coomera", "maroochydore", "caloundra",
    "noosa", "nambour", "beenleigh", "capalaba", "cleveland", "chermside", "fortitude valley",
    "newstead", "south brisbane", "milton", "bowen hills", "west end", "woolloongabba",
    "eight mile plains", "springwood", "underwood", "slacks creek", "yatala", "brendale",
    "strathpine", "murarrie", "hemmant", "eagle farm", "pinkenba", "hendra", "toowong",
    "indooroopilly", "mount gravatt", "mt gravatt", "carindale", "spring hill", "kangaroo point",
]
OTHER_CITIES = [
    "sydney", "nsw", "melbourne", "vic", "victoria", "perth", " wa", "adelaide", " sa",
    "darwin", "hobart", "tasmania", "canberra", "act", "cairns", "townsville", "mackay",
    "rockhampton", "auckland", "new zealand",
]


# =====================================================================
# Data model
# =====================================================================
@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted: Optional[date] = None
    salary: str = ""
    snippet: str = ""
    work_type: str = ""
    score: int = 0
    reasons: List[str] = field(default_factory=list)
    is_new: bool = False
    sources: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Identity used for de-duplication and the 'new since last run' flag."""
        return dedupe_key(self.title, self.company)

    def age_days(self, today: Optional[date] = None) -> Optional[int]:
        if not self.posted:
            return None
        return ((today or date.today()) - self.posted).days


def dedupe_key(title: str, company: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    c = re.sub(r"\b(pty|ltd|limited|group|australia|qld|the)\b", " ", (company or "").lower())
    c = re.sub(r"[^a-z0-9]+", " ", c).strip()
    return f"{t}|{c}"


# =====================================================================
# Small helpers
# =====================================================================
_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(s: object) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if s is None:
        return ""
    s = html.unescape(_TAG_RE.sub(" ", str(s)))
    return re.sub(r"\s+", " ", s).strip()


def parse_date(value: object) -> Optional[date]:
    """Parse the date formats the APIs return (ISO 8601, with or without time)."""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def money(n: object) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    if v < 500:  # hourly rate
        return f"${v:,.0f}/hr"
    return f"${v / 1000:,.0f}k"


def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, default=str)
    os.replace(tmp, path)


def http_json(url: str, payload: Optional[dict] = None, timeout: float = 25.0):
    """GET (or POST JSON when payload is given) and decode a JSON response."""
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def selected_terms(group_names: Iterable[str], custom: str = "") -> List[str]:
    names = set(group_names)
    terms: List[str] = []
    for g in ROLE_GROUPS:
        if g["name"] in names:
            terms.extend(g["terms"])
    for t in re.split(r"[,;\n]+", custom or ""):
        t = t.strip()
        if t:
            terms.append(t)
    seen = set()
    out = []
    for t in terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


# =====================================================================
# Sources (official APIs only)
# =====================================================================
Log = Callable[[str], None]


class SourceError(Exception):
    pass


ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/au/search/{page}"
# Adzuna's free tier allows roughly 25 calls a minute; stay under it.
ADZUNA_MIN_INTERVAL = 2.6


def _adzuna_job(r: dict) -> Job:
    sal = ""
    lo, hi = money(r.get("salary_min")), money(r.get("salary_max"))
    if lo and hi and lo != hi:
        sal = f"{lo}-{hi}"
    else:
        sal = lo or hi
    if sal and str(r.get("salary_is_predicted", "0")) == "1":
        sal += " (est.)"
    wt = " ".join(x for x in [r.get("contract_time") or "", r.get("contract_type") or ""] if x)
    return Job(
        title=clean_text(r.get("title")),
        company=clean_text((r.get("company") or {}).get("display_name")),
        location=clean_text((r.get("location") or {}).get("display_name")),
        url=r.get("redirect_url") or "",
        source="Adzuna",
        posted=parse_date(r.get("created")),
        salary=sal,
        snippet=clean_text(r.get("description"))[:600],
        work_type=wt.replace("_", " "),
    )


def search_adzuna(app_id: str, app_key: str, terms: Sequence[str], where: str,
                  distance_km: int, days: int, exclude: Sequence[str], log: Log,
                  cancel: Optional[threading.Event] = None) -> List[Job]:
    """One call per multi-word term, single words batched into one OR query."""
    if not (app_id and app_key):
        return []
    single = [t for t in terms if " " not in t.strip()]
    multi = [t for t in terms if " " in t.strip()]
    queries: List[Tuple[str, dict]] = []
    if single:
        queries.append((" / ".join(single), {"what_or": " ".join(single)}))
    for t in multi:
        queries.append((t, {"what": t}))

    jobs: List[Job] = []
    last_call = 0.0
    for label, q in queries:
        if cancel is not None and cancel.is_set():
            break
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 50,
            "where": where,
            "distance": max(1, int(distance_km)),
            "max_days_old": max(1, int(days)),
            "sort_by": "date",
            "content-type": "application/json",
        }
        params.update(q)
        if exclude:
            params["what_exclude"] = " ".join(exclude)
        url = ADZUNA_URL.format(page=1) + "?" + urllib.parse.urlencode(params)
        wait = ADZUNA_MIN_INTERVAL - (time.time() - last_call)
        if wait > 0:
            time.sleep(wait)
        last_call = time.time()
        try:
            data = http_json(url)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SourceError("Adzuna rejected the app_id/app_key. Check them under API keys.")
            if e.code == 429:
                log("Adzuna: rate limit reached - stopping Adzuna for this run.")
                break
            log(f"Adzuna: '{label}' failed (HTTP {e.code}).")
            continue
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"Adzuna: '{label}' failed ({e}).")
            continue
        results = data.get("results") or []
        jobs.extend(_adzuna_job(r) for r in results)
        log(f"Adzuna: '{label}' in {where} -> {len(results)}")
    return jobs


JOOBLE_URL = "https://jooble.org/api/{key}"


def _jooble_job(r: dict) -> Job:
    return Job(
        title=clean_text(r.get("title")),
        company=clean_text(r.get("company")),
        location=clean_text(r.get("location")),
        url=r.get("link") or "",
        source="Jooble" + (f" / {clean_text(r.get('source'))}" if r.get("source") else ""),
        posted=parse_date(r.get("updated")),
        salary=clean_text(r.get("salary")),
        snippet=clean_text(r.get("snippet"))[:600],
        work_type=clean_text(r.get("type")),
    )


def search_jooble(api_key: str, terms: Sequence[str], where: str, distance_km: int,
                  days: int, log: Log, cancel: Optional[threading.Event] = None) -> List[Job]:
    if not api_key:
        return []
    jobs: List[Job] = []
    since = (date.today() - timedelta(days=max(1, int(days)))).isoformat()
    for t in terms:
        if cancel is not None and cancel.is_set():
            break
        payload = {
            "keywords": t,
            "location": f"{where} QLD",
            "radius": str(max(1, int(distance_km))),
            "page": "1",
            "ResultOnPage": "50",
            "datecreatedfrom": since,
        }
        try:
            data = http_json(JOOBLE_URL.format(key=urllib.parse.quote(api_key)), payload)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SourceError("Jooble rejected the API key. Check it under API keys.")
            log(f"Jooble: '{t}' failed (HTTP {e.code}).")
            continue
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"Jooble: '{t}' failed ({e}).")
            continue
        results = data.get("jobs") or []
        jobs.extend(_jooble_job(r) for r in results)
        log(f"Jooble: '{t}' in {where} -> {len(results)}")
        time.sleep(0.4)
    return jobs


# =====================================================================
# Ranking
# =====================================================================
# (pattern, points, label) matched against the job TITLE.
TITLE_RULES: List[Tuple[str, int, str]] = [
    (r"\bdrafting (manager|team ?leader|lead|supervisor|coordinator)\b", 60, "drafting management"),
    (r"\b(building|home|house|residential) design(er)?\b", 55, "building design"),
    (r"\barchicad\b", 55, "Archicad in title"),
    (r"\bdraft(s?person|sman|swoman|er|ing)\b", 50, "drafting"),
    (r"\bhead of (design|drafting|product)\b", 50, "head of design/product"),
    (r"\bdesign (and|&) (documentation|development) manager\b", 50, "design & documentation"),
    (r"\barchitectural (designer|technician|documenter|technologist|draft)", 50, "architectural documentation"),
    (r"\bdesign (manager|coordinator|lead|team ?leader|director)\b", 42, "design management"),
    (r"\bproduct (development|design) (manager|coordinator|lead|specialist)\b", 42, "product development"),
    (r"\bbim (modell?er|coordinator|manager|technician|lead)\b", 38, "BIM"),
    (r"\bcad (drafter|technician|operator|manager|designer)\b", 38, "CAD"),
    (r"\brevit\b", 32, "Revit in title"),
    (r"\bproduct manager\b", 25, "product manager"),
    (r"\bstudio manager\b", 25, "studio manager"),
    (r"\b(estimator|contracts? administrator|pre-?start|energy assessor|certifier)\b", 15, "adjacent role"),
]

# Matched against title + description: (pattern, points, label)
CONTEXT_RULES: List[Tuple[str, int, str]] = [
    (r"\barchicad\b", 15, "mentions Archicad"),
    (r"\b(volume|project) (home )?builder|\bnew homes?\b|\bhome builder\b", 8, "home builder"),
    (r"\b(design range|product range|house designs?|display homes?|house (and|&) land)\b", 8,
     "house design range"),
    (r"\bresidential\b", 6, "residential"),
    (r"\brevit\b", 5, "mentions Revit"),
    (r"\b(working|construction) (drawings|documentation)\b", 4, "construction documentation"),
    (r"\b(ncc|bca|qdc|qbcc|national construction code)\b", 4, "codes (NCC/QDC/QBCC)"),
    (r"\bautocad\b", 2, "mentions AutoCAD"),
]

BUILDING_CONTEXT = re.compile(
    r"\b(home|homes|house|houses|residential|building|construction|builder|architect\w*|"
    r"floor ?plans?|facade|façade|townhouse|dwelling|bathroom|kitchen|joinery|roofing|cladding|"
    r"windows?|doors?|timber|steel framing|frame|truss)\b"
)
NEGATIVE_TITLE = re.compile(
    r"\b(civil|mechanical|electrical|piping|hydraulic|mining|rail|road|structural steel|"
    r"software|digital|saas|data|fmcg|food|fashion|apparel|pharma\w*|medical|automotive|"
    r"marketing|graphic|ux|ui|web|game|insurance|banking|retail buyer)\b"
)


def score_job(job: Job, today: Optional[date] = None) -> Job:
    title = job.title.lower()
    text = f"{job.title} {job.snippet}".lower()
    reasons: List[str] = []

    best = 0
    best_label = ""
    for pat, pts, label in TITLE_RULES:
        if re.search(pat, title) and pts > best:
            best, best_label = pts, label
    score = best
    if best_label:
        reasons.append(f"title: {best_label}")

    ctx = 0
    for pat, pts, label in CONTEXT_RULES:
        if re.search(pat, text):
            ctx += pts
            reasons.append(label)
    score += min(ctx, 30)

    if "product" in best_label and not BUILDING_CONTEXT.search(text):
        score -= 35
        reasons.append("product role outside building (-)")
    if NEGATIVE_TITLE.search(title):
        score -= 40
        reasons.append("off-target discipline (-)")

    loc = f" {job.location.lower()} "
    if any(p in loc for p in SEQ_PLACES):
        score += 5
        reasons.append("SEQ location")
    elif any(c in loc for c in OTHER_CITIES):
        score -= 40
        reasons.append("outside SEQ (-)")

    age = job.age_days(today)
    if age is not None and age <= 3:
        score += 5
        reasons.append("posted in last 3 days")

    job.score = max(0, min(100, score))
    job.reasons = reasons
    return job


def dedupe(jobs: Iterable[Job]) -> List[Job]:
    by_key: Dict[str, Job] = {}
    for j in jobs:
        if not j.title or not j.url:
            continue
        k = j.key
        cur = by_key.get(k)
        if cur is None:
            j.sources = [j.source]
            by_key[k] = j
            continue
        if j.source not in cur.sources:
            cur.sources.append(j.source)
        # keep the richer record's fields
        if not cur.salary and j.salary:
            cur.salary = j.salary
        if len(j.snippet) > len(cur.snippet):
            cur.snippet = j.snippet
        if j.posted and (not cur.posted or j.posted > cur.posted):
            cur.posted = j.posted
    return list(by_key.values())


def mark_new(jobs: List[Job], seen_path: str = SEEN_PATH, remember: bool = True) -> int:
    """Flag jobs not seen in a previous run. Returns the count of new jobs."""
    seen: Dict[str, str] = load_json(seen_path, {})
    today = date.today().isoformat()
    n = 0
    for j in jobs:
        if j.key not in seen:
            j.is_new = True
            n += 1
            if remember:
                seen[j.key] = today
    if remember:
        # forget entries older than 120 days so the file stays small
        cutoff = (date.today() - timedelta(days=120)).isoformat()
        seen = {k: v for k, v in seen.items() if v >= cutoff}
        try:
            save_json(seen_path, seen)
        except OSError:
            pass
    return n


# =====================================================================
# Board deep links (no keys needed)
# =====================================================================
# URL formats checked October 2026. SEEK's search now lives on au.seek.com.
DAYS_TO_LINKEDIN = {1: "r86400", 3: "r259200", 7: "r604800", 14: "r1209600", 30: "r2592000"}
DAYS_TO_GOOGLE = {1: " since yesterday", 3: " in the last 3 days", 7: " in the last week",
                  14: " in the last 2 weeks", 30: " in the last month"}
KM_TO_LINKEDIN_MILES = {10: 5, 25: 10, 50: 25, 100: 50}
GOOGLE_MAX_TERMS = 6  # Google reads only the first 32 words of a query


def boolean_query(terms: Sequence[str], exclude: Sequence[str] = (), style: str = "seek") -> str:
    """SEEK/LinkedIn style: (a OR "b c") NOT x NOT y.  Indeed/Google style: ... -x -y."""
    quote = lambda t: f'"{t}"' if re.search(r"[\s\-&/]", t) else t  # noqa: E731
    parts = [quote(t) for t in terms]
    q = "(" + " OR ".join(parts) + ")" if len(parts) > 1 else (parts[0] if parts else "")
    if exclude:
        if style == "indeed":
            q += " " + " ".join(f"-{quote(x)}" for x in exclude)
        else:
            q += " " + " ".join(f"NOT {quote(x)}" for x in exclude)
    return q


def board_search_urls(terms: Sequence[str], location: str = "Brisbane", days: int = 7,
                      radius_km: int = 50, exclude: Sequence[str] = ()) -> List[Tuple[str, str]]:
    """Searches on the boards that understand OR queries, plus SEEK's drafting category."""
    loc = LOCATIONS.get(location, LOCATIONS["Brisbane"])
    q_seek = boolean_query(terms, exclude, "seek")
    q_indeed = boolean_query(terms, exclude, "indeed")
    q_google = boolean_query(terms[:GOOGLE_MAX_TERMS], exclude[:3], "indeed")
    seek_days = min([d for d in (1, 3, 7, 14, 31) if d >= days] or [31])
    miles = KM_TO_LINKEDIN_MILES.get(radius_km) or min(KM_TO_LINKEDIN_MILES.values(),
                                                         key=lambda m: abs(m * 1.6 - radius_km))
    seek_place = urllib.parse.quote(loc["seek"].replace(" ", "-"), safe="&-")
    return [
        ("SEEK", "https://au.seek.com/jobs?" + urllib.parse.urlencode({
            "keywords": q_seek, "where": loc["seek"], "daterange": seek_days,
            "sortmode": "ListedDate"})),
        ("SEEK Architectural Drafting", f"https://au.seek.com/jobs-in-design-architecture/"
            f"architectural-drafting/in-{seek_place}?" + urllib.parse.urlencode({
                "daterange": seek_days, "sortmode": "ListedDate"})),
        ("Indeed", "https://au.indeed.com/jobs?" + urllib.parse.urlencode({
            "q": q_indeed, "l": loc["label"], "radius": radius_km, "fromage": days,
            "sort": "date"})),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode({
            "keywords": q_seek, "location": f"{loc['where']}, Queensland, Australia",
            "distance": miles, "f_TPR": DAYS_TO_LINKEDIN.get(days, "r604800"), "sortBy": "DD"})),
        ("Google Jobs", "https://www.google.com/search?" + urllib.parse.urlencode({
            "q": f"{q_google} jobs in {loc['label']}{DAYS_TO_GOOGLE.get(days, '')}", "udm": "8"})),
    ]


# =====================================================================
# Running a search
# =====================================================================
@dataclass
class SearchParams:
    groups: List[str]
    custom: str = ""
    locations: List[str] = field(default_factory=lambda: ["Brisbane"])
    radius_km: int = 50
    days: int = 7
    exclude: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    min_score: int = 25


def load_config() -> dict:
    cfg = load_json(CONFIG_PATH, {})
    # environment variables win, so keys never have to live in a file
    for env, key in (("ADZUNA_APP_ID", "adzuna_app_id"), ("ADZUNA_APP_KEY", "adzuna_app_key"),
                     ("JOOBLE_API_KEY", "jooble_key")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def has_keys(cfg: dict) -> bool:
    return bool((cfg.get("adzuna_app_id") and cfg.get("adzuna_app_key")) or cfg.get("jooble_key"))


def run_search(p: SearchParams, cfg: dict, log: Log = print,
               cancel: Optional[threading.Event] = None, remember: bool = True) -> List[Job]:
    terms = selected_terms(p.groups, p.custom)
    if not terms:
        log("Pick at least one role group or type a keyword.")
        return []
    raw: List[Job] = []
    for loc_name in p.locations:
        where = LOCATIONS.get(loc_name, {"where": loc_name})["where"]
        try:
            raw += search_adzuna(cfg.get("adzuna_app_id", ""), cfg.get("adzuna_app_key", ""),
                                 terms, where, p.radius_km, p.days, p.exclude, log, cancel)
        except SourceError as e:
            log(str(e))
        try:
            raw += search_jooble(cfg.get("jooble_key", ""), terms, where, p.radius_km, p.days,
                                 log, cancel)
        except SourceError as e:
            log(str(e))
    jobs = dedupe(raw)
    today = date.today()
    cutoff = today - timedelta(days=p.days)
    jobs = [score_job(j, today) for j in jobs if not j.posted or j.posted >= cutoff]
    jobs = [j for j in jobs if j.score >= p.min_score]
    n_new = mark_new(jobs, remember=remember)
    jobs.sort(key=lambda j: (j.is_new, j.score, j.posted or date.min), reverse=True)
    log(f"Done: {len(raw)} ads fetched, {len(jobs)} relevant after ranking, {n_new} new.")
    return jobs


# =====================================================================
# Export
# =====================================================================
EXPORT_FIELDS = ["new", "score", "title", "company", "location", "salary", "posted",
                 "work_type", "sources", "url", "why"]


def job_row(j: Job) -> dict:
    return {
        "new": "NEW" if j.is_new else "",
        "score": j.score,
        "title": j.title,
        "company": j.company,
        "location": j.location,
        "salary": j.salary,
        "posted": j.posted.isoformat() if j.posted else "",
        "work_type": j.work_type,
        "sources": ", ".join(j.sources or [j.source]),
        "url": j.url,
        "why": "; ".join(j.reasons),
    }


def export_csv(jobs: Sequence[Job], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        w.writeheader()
        for j in jobs:
            w.writerow(job_row(j))


def export_html(jobs: Sequence[Job], path: str) -> None:
    e = html.escape
    rows = []
    for j in jobs:
        r = job_row(j)
        rows.append(
            "<tr{cls}><td class=n>{new}</td><td class=s>{score}</td>"
            "<td><a href=\"{url}\">{title}</a><div class=why>{why}</div></td>"
            "<td>{company}</td><td>{location}</td><td>{salary}</td><td class=d>{posted}</td>"
            "<td>{sources}</td></tr>".format(
                cls=" class=new" if j.is_new else "",
                **{k: e(str(v)) for k, v in r.items()}))
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    doc = f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{APP_NAME} - {stamp}</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#16212b;background:#f5f7f6}}
h1{{font-size:20px;margin:0 0 4px}} p{{margin:0 0 16px;color:#4a5866}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border-bottom:1px solid #d6dde2;padding:8px;text-align:left;vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#4a5866}}
a{{color:#1f5a93;font-weight:600}} .why{{font-size:12px;color:#6b7782}}
.n{{color:#c23b22;font-weight:700}} .s,.d{{font-variant-numeric:tabular-nums;white-space:nowrap}}
tr.new td{{background:#fff6f3}}
</style>
<h1>{APP_NAME}</h1><p>{len(jobs)} jobs &middot; generated {e(stamp)}</p>
<div class=wrap><table><tr><th>New</th><th>Fit</th><th>Role</th><th>Company</th>
<th>Location</th><th>Salary</th><th>Posted</th><th>Source</th></tr>
{''.join(rows)}</table></div>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


# =====================================================================
# Command line
# =====================================================================
def cli(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} (headless mode)")
    ap.add_argument("--cli", action="store_true", help="run without the window")
    ap.add_argument("--groups", nargs="*", default=[g["name"] for g in ROLE_GROUPS if g["default"]],
                    help="role groups to search (default: all except Adjacent roles)")
    ap.add_argument("--keywords", default="", help="extra keywords, comma separated")
    ap.add_argument("--locations", nargs="*", default=["Brisbane"], choices=list(LOCATIONS))
    ap.add_argument("--radius", type=int, default=50, help="radius in km (default 50)")
    ap.add_argument("--days", type=int, default=7, help="posted within N days (default 7)")
    ap.add_argument("--min-score", type=int, default=25)
    ap.add_argument("--csv", help="write results to this CSV file")
    ap.add_argument("--html", help="write results to this HTML file")
    ap.add_argument("--links", action="store_true", help="print board search links and exit")
    a = ap.parse_args(argv)

    p = SearchParams(groups=a.groups, custom=a.keywords, locations=a.locations,
                     radius_km=a.radius, days=a.days, min_score=a.min_score)
    terms = selected_terms(p.groups, p.custom)
    if a.links:
        for loc in p.locations:
            for name, url in board_search_urls(terms, loc, p.days, p.radius_km, p.exclude):
                print(f"{name} ({loc}): {url}")
        return 0

    cfg = load_config()
    if not has_keys(cfg):
        print("No API keys found. Set ADZUNA_APP_ID / ADZUNA_APP_KEY and/or JOOBLE_API_KEY,\n"
              f"or save them from the window (they go to {CONFIG_PATH}).\n"
              "Board search links instead:\n")
        for name, url in board_search_urls(terms, p.locations[0], p.days, p.radius_km, p.exclude):
            print(f"  {name}: {url}")
        return 1
    jobs = run_search(p, cfg, log=lambda m: print(m, file=sys.stderr))
    for j in jobs:
        flag = "NEW " if j.is_new else "    "
        posted = j.posted.strftime("%d %b") if j.posted else "      "
        print(f"{flag}{j.score:>3}  {posted}  {j.title[:60]:<60}  {j.company[:28]:<28}  {j.url}")
    if a.csv:
        export_csv(jobs, a.csv)
        print(f"Saved {a.csv}", file=sys.stderr)
    if a.html:
        export_html(jobs, a.html)
        print(f"Saved {a.html}", file=sys.stderr)
    return 0


# =====================================================================
# Window (tkinter)
# =====================================================================
def gui() -> None:
    import queue
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    cfg = load_config()
    state = load_json(CONFIG_PATH, {}).get("last_search", {})

    root = tk.Tk()
    root.title(f"{APP_NAME} - live search")
    root.geometry("1280x800")
    root.minsize(960, 600)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Treeview", rowheight=24)
    style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"))
    style.configure("Muted.TLabel", foreground="#4a5866")

    msgs: "queue.Queue[tuple]" = queue.Queue()
    cancel = threading.Event()
    results: List[Job] = []
    sort_state = {"col": None, "rev": False}

    # ---------- top: controls ----------
    top = ttk.Frame(root, padding=(12, 10, 12, 6))
    top.pack(fill="x")
    ttk.Label(top, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(top, text="Building design · drafting · Archicad · design & product management · Brisbane / SEQ",
              style="Muted.TLabel").grid(row=0, column=1, columnspan=3, sticky="w", padx=(12, 0))

    roles = ttk.LabelFrame(top, text="Roles", padding=8)
    roles.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
    group_vars: Dict[str, tk.BooleanVar] = {}
    saved_groups = state.get("groups")
    for i, g in enumerate(ROLE_GROUPS):
        on = (g["name"] in saved_groups) if saved_groups is not None else g["default"]
        v = tk.BooleanVar(value=on)
        group_vars[g["name"]] = v
        ttk.Checkbutton(roles, text=f"{g['name']} ({len(g['terms'])})", variable=v).grid(
            row=i // 2, column=i % 2, sticky="w", padx=(0, 14))
    ttk.Label(roles, text="Extra keywords (comma separated):").grid(row=3, column=0, columnspan=2,
                                                                    sticky="w", pady=(6, 0))
    custom_var = tk.StringVar(value=state.get("custom", ""))
    ttk.Entry(roles, textvariable=custom_var, width=48).grid(row=4, column=0, columnspan=2, sticky="we")

    where = ttk.LabelFrame(top, text="Where & when", padding=8)
    where.grid(row=1, column=1, sticky="nsew", padx=10, pady=(8, 0))
    loc_vars: Dict[str, tk.BooleanVar] = {}
    saved_locs = state.get("locations", ["Brisbane"])
    for i, name in enumerate(LOCATIONS):
        v = tk.BooleanVar(value=name in saved_locs)
        loc_vars[name] = v
        ttk.Checkbutton(where, text=name, variable=v).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
    ttk.Label(where, text="Radius (km)").grid(row=2, column=0, sticky="w", pady=(6, 0))
    radius_var = tk.StringVar(value=str(state.get("radius_km", 50)))
    ttk.Combobox(where, textvariable=radius_var, values=["10", "25", "50", "100"], width=6,
                 state="readonly").grid(row=2, column=1, sticky="w", pady=(6, 0))
    ttk.Label(where, text="Posted within (days)").grid(row=3, column=0, sticky="w")
    days_var = tk.StringVar(value=str(state.get("days", 7)))
    ttk.Combobox(where, textvariable=days_var, values=["1", "3", "7", "14", "30"], width=6,
                 state="readonly").grid(row=3, column=1, sticky="w")
    ttk.Label(where, text="Exclude words").grid(row=4, column=0, sticky="w")
    exclude_var = tk.StringVar(value=", ".join(state.get("exclude", DEFAULT_EXCLUDE)))
    ttk.Entry(where, textvariable=exclude_var, width=28).grid(row=4, column=1, sticky="w")

    acts = ttk.LabelFrame(top, text="Actions", padding=8)
    acts.grid(row=1, column=2, sticky="nsew", pady=(8, 0))
    search_btn = ttk.Button(acts, text="Search live listings")
    search_btn.grid(row=0, column=0, sticky="we", pady=2)
    boards_btn = ttk.Button(acts, text="Open board searches")
    boards_btn.grid(row=1, column=0, sticky="we", pady=2)
    keys_btn = ttk.Button(acts, text="API keys…")
    keys_btn.grid(row=2, column=0, sticky="we", pady=2)
    exp_csv = ttk.Button(acts, text="Export CSV…")
    exp_csv.grid(row=0, column=1, sticky="we", padx=(6, 0), pady=2)
    exp_html = ttk.Button(acts, text="Export HTML…")
    exp_html.grid(row=1, column=1, sticky="we", padx=(6, 0), pady=2)
    ttk.Label(acts, text="Min fit score").grid(row=2, column=1, sticky="w", padx=(6, 0))
    min_var = tk.IntVar(value=int(state.get("min_score", 25)))
    ttk.Scale(acts, from_=0, to=80, variable=min_var, orient="horizontal").grid(
        row=3, column=0, columnspan=2, sticky="we")
    min_lbl = ttk.Label(acts, text="")
    min_lbl.grid(row=4, column=0, columnspan=2, sticky="w")
    top.columnconfigure(3, weight=1)

    # ---------- filter row ----------
    fbar = ttk.Frame(root, padding=(12, 4))
    fbar.pack(fill="x")
    ttk.Label(fbar, text="Filter results:").pack(side="left")
    filter_var = tk.StringVar()
    ttk.Entry(fbar, textvariable=filter_var, width=36).pack(side="left", padx=6)
    only_new = tk.BooleanVar(value=False)
    ttk.Checkbutton(fbar, text="Only new", variable=only_new).pack(side="left", padx=6)
    count_lbl = ttk.Label(fbar, text="", style="Muted.TLabel")
    count_lbl.pack(side="right")

    # ---------- results ----------
    body = ttk.PanedWindow(root, orient="vertical")
    body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    table_frame = ttk.Frame(body)
    cols = ("new", "score", "title", "company", "location", "salary", "posted", "source")
    heads = {"new": "New", "score": "Fit", "title": "Role", "company": "Company",
             "location": "Location", "salary": "Salary", "posted": "Posted", "source": "Source"}
    widths = {"new": 46, "score": 46, "title": 360, "company": 200, "location": 170,
              "salary": 120, "posted": 80, "source": 140}
    tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
    for c in cols:
        tree.heading(c, text=heads[c], command=lambda c=c: sort_by(c))
        tree.column(c, width=widths[c], anchor="w", stretch=c in ("title", "company"))
    tree.tag_configure("new", foreground="#c23b22")
    tree.tag_configure("strong", font=("Segoe UI", 9, "bold"))
    vs = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vs.set)
    tree.pack(side="left", fill="both", expand=True)
    vs.pack(side="right", fill="y")
    body.add(table_frame, weight=4)

    detail = tk.Text(body, height=7, wrap="word", relief="flat", padx=10, pady=8,
                     background="#f5f7f6", foreground="#16212b")
    detail.configure(state="disabled")
    body.add(detail, weight=1)

    status_var = tk.StringVar()
    ttk.Label(root, textvariable=status_var, anchor="w", padding=(12, 4),
              style="Muted.TLabel").pack(fill="x")

    def set_status(msg: str) -> None:
        status_var.set(msg)

    def update_min_label(*_):
        min_lbl.configure(text=f"Hide fit below {int(min_var.get())}")
        refresh()

    def current_params() -> SearchParams:
        excl = [x.strip() for x in exclude_var.get().split(",") if x.strip()]
        return SearchParams(
            groups=[n for n, v in group_vars.items() if v.get()],
            custom=custom_var.get(),
            locations=[n for n, v in loc_vars.items() if v.get()] or ["Brisbane"],
            radius_km=int(radius_var.get() or 50),
            days=int(days_var.get() or 7),
            exclude=excl,
            min_score=0,  # filter in the window instead, so the slider is live
        )

    def remember_state(p: SearchParams) -> None:
        data = load_json(CONFIG_PATH, {})
        data["last_search"] = {"groups": p.groups, "custom": p.custom, "locations": p.locations,
                               "radius_km": p.radius_km, "days": p.days, "exclude": p.exclude,
                               "min_score": int(min_var.get())}
        try:
            save_json(CONFIG_PATH, data)
        except OSError:
            pass

    def visible_jobs() -> List[Job]:
        f = filter_var.get().strip().lower()
        out = []
        for j in results:
            if j.score < int(min_var.get()):
                continue
            if only_new.get() and not j.is_new:
                continue
            if f and f not in f"{j.title} {j.company} {j.location} {j.snippet}".lower():
                continue
            out.append(j)
        return out

    def refresh(*_):
        tree.delete(*tree.get_children())
        shown = visible_jobs()
        for idx, j in enumerate(shown):
            tags = []
            if j.is_new:
                tags.append("new")
            if j.score >= 60:
                tags.append("strong")
            tree.insert("", "end", iid=str(id(j)), values=(
                "NEW" if j.is_new else "", j.score, j.title, j.company, j.location, j.salary,
                j.posted.strftime("%d %b") if j.posted else "", ", ".join(j.sources or [j.source]),
            ), tags=tags)
        n_new = sum(1 for j in results if j.is_new)
        count_lbl.configure(text=f"{len(shown)} shown · {len(results)} found · {n_new} new")

    def job_for(iid: str) -> Optional[Job]:
        for j in results:
            if str(id(j)) == iid:
                return j
        return None

    def on_select(_evt=None):
        sel = tree.selection()
        j = job_for(sel[0]) if sel else None
        detail.configure(state="normal")
        detail.delete("1.0", "end")
        if j:
            detail.insert("end", f"{j.title} — {j.company}\n", ("h",))
            detail.insert("end", f"{j.location}   {j.salary}   {j.work_type}\n")
            detail.insert("end", f"Why it ranked {j.score}: {', '.join(j.reasons) or 'keyword match'}\n\n")
            detail.insert("end", j.snippet + "\n\n")
            detail.insert("end", "Double-click the row to open the ad.  " + j.url)
            detail.tag_configure("h", font=("Segoe UI", 11, "bold"))
        detail.configure(state="disabled")

    def on_open(_evt=None):
        sel = tree.selection()
        j = job_for(sel[0]) if sel else None
        if j and j.url:
            webbrowser.open_new_tab(j.url)

    def sort_by(col: str):
        rev = not sort_state["rev"] if sort_state["col"] == col else col in ("score", "posted", "new")
        sort_state.update(col=col, rev=rev)
        keyf = {
            "new": lambda j: j.is_new, "score": lambda j: j.score,
            "title": lambda j: j.title.lower(), "company": lambda j: j.company.lower(),
            "location": lambda j: j.location.lower(), "salary": lambda j: j.salary,
            "posted": lambda j: j.posted or date.min,
            "source": lambda j: ",".join(j.sources or [j.source]),
        }[col]
        results.sort(key=keyf, reverse=rev)
        refresh()

    def worker(p: SearchParams, conf: dict):
        try:
            jobs = run_search(p, conf, log=lambda m: msgs.put(("log", m)), cancel=cancel)
            msgs.put(("done", jobs))
        except Exception as ex:  # surface anything unexpected in the window
            msgs.put(("error", f"{type(ex).__name__}: {ex}"))

    def poll():
        try:
            while True:
                kind, payload = msgs.get_nowait()
                if kind == "log":
                    set_status(payload)
                elif kind == "done":
                    results[:] = payload
                    refresh()
                    search_btn.configure(text="Search live listings", state="normal")
                elif kind == "error":
                    search_btn.configure(text="Search live listings", state="normal")
                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        root.after(150, poll)

    def start_search():
        nonlocal cfg
        cfg = load_config()
        if not has_keys(cfg):
            if messagebox.askyesno(
                    APP_NAME,
                    "Live listings need a free Adzuna or Jooble API key.\n\n"
                    "Add keys now? (Choose No to open the board searches in your browser instead.)"):
                open_keys()
            else:
                open_boards()
            return
        p = current_params()
        if not selected_terms(p.groups, p.custom):
            messagebox.showinfo(APP_NAME, "Tick at least one role group or type a keyword.")
            return
        remember_state(p)
        cancel.clear()
        search_btn.configure(text="Searching…", state="disabled")
        set_status("Searching…")
        threading.Thread(target=worker, args=(p, cfg), daemon=True).start()

    def open_boards():
        p = current_params()
        terms = selected_terms(p.groups, p.custom)
        if not terms:
            messagebox.showinfo(APP_NAME, "Tick at least one role group or type a keyword.")
            return
        remember_state(p)
        for name, url in board_search_urls(terms, p.locations[0], p.days, p.radius_km, p.exclude):
            webbrowser.open_new_tab(url)
            time.sleep(0.25)
        set_status(f"Opened {len(terms)}-keyword searches for {p.locations[0]} on SEEK, Indeed, "
                   "LinkedIn and Google Jobs.")

    def open_keys():
        win = tk.Toplevel(root)
        win.title("API keys")
        win.transient(root)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        data = load_json(CONFIG_PATH, {})
        fields = [("Adzuna app_id", "adzuna_app_id"), ("Adzuna app_key", "adzuna_app_key"),
                  ("Jooble API key", "jooble_key")]
        vars_: Dict[str, tk.StringVar] = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=data.get(key, ""))
            vars_[key] = v
            ttk.Entry(frm, textvariable=v, width=44).grid(row=i, column=1, sticky="we", pady=3)
        ttk.Label(frm, text="Both are free. Keys are saved next to this script in\n"
                            f"{os.path.basename(CONFIG_PATH)} (keep that file private).",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 4))
        links = ttk.Frame(frm)
        links.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Button(links, text="Get Adzuna keys",
                   command=lambda: webbrowser.open_new_tab("https://developer.adzuna.com/signup")
                   ).pack(side="left")
        ttk.Button(links, text="Get Jooble key",
                   command=lambda: webbrowser.open_new_tab("https://jooble.org/api/about")
                   ).pack(side="left", padx=6)

        def save():
            d = load_json(CONFIG_PATH, {})
            for key, v in vars_.items():
                d[key] = v.get().strip()
            try:
                save_json(CONFIG_PATH, d)
            except OSError as ex:
                messagebox.showerror(APP_NAME, f"Couldn't save keys: {ex}")
                return
            win.destroy()
            set_status("Keys saved. Press 'Search live listings'.")

        ttk.Button(frm, text="Save", command=save).grid(row=5, column=1, sticky="e", pady=(12, 0))

    def do_export(kind: str):
        shown = visible_jobs()
        if not shown:
            messagebox.showinfo(APP_NAME, "Nothing to export yet. Run a search first.")
            return
        ext = ".csv" if kind == "csv" else ".html"
        path = filedialog.asksaveasfilename(
            defaultextension=ext, initialfile=f"brisbane_design_jobs_{date.today():%Y-%m-%d}{ext}",
            filetypes=[("CSV", "*.csv")] if kind == "csv" else [("HTML", "*.html")])
        if not path:
            return
        (export_csv if kind == "csv" else export_html)(shown, path)
        set_status(f"Saved {len(shown)} jobs to {path}")

    search_btn.configure(command=start_search)
    boards_btn.configure(command=open_boards)
    keys_btn.configure(command=open_keys)
    exp_csv.configure(command=lambda: do_export("csv"))
    exp_html.configure(command=lambda: do_export("html"))
    tree.bind("<<TreeviewSelect>>", on_select)
    tree.bind("<Double-1>", on_open)
    tree.bind("<Return>", on_open)
    filter_var.trace_add("write", refresh)
    only_new.trace_add("write", refresh)
    min_var.trace_add("write", update_min_label)
    update_min_label()

    if has_keys(cfg):
        set_status("Ready. Press 'Search live listings'.")
    else:
        set_status("No API keys yet: 'Open board searches' works now; add free keys for live listings.")
    root.after(150, poll)
    root.mainloop()


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        return cli(argv)
    try:
        gui()
    except ImportError:
        print("tkinter isn't available; running in command-line mode.\n", file=sys.stderr)
        return cli(["--cli"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
