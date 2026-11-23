"""Tests for brisbane_design_jobs (no network: API calls are mocked).

Run:  python -m unittest job_search/test_brisbane_design_jobs.py
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brisbane_design_jobs as bdj  # noqa: E402

TODAY = date.today()


def job(title, company="Acme Homes", location="Brisbane, QLD", snippet="", posted=None, url=None):
    return bdj.Job(title=title, company=company, location=location, snippet=snippet,
                   posted=posted or TODAY, url=url or f"https://example.com/{title}", source="Test")


class RankingTests(unittest.TestCase):
    def score(self, *a, **k):
        return bdj.score_job(job(*a, **k), TODAY).score

    def test_core_roles_rank_high(self):
        self.assertGreaterEqual(self.score("Building Designer", snippet="Archicad, residential"), 70)
        self.assertGreaterEqual(self.score("Senior Draftsperson - Archicad"), 60)
        self.assertGreaterEqual(self.score("Drafting Manager", snippet="volume builder new homes"), 70)

    def test_product_role_needs_building_context(self):
        homes = self.score("Product Development Manager", snippet="house design range for our homes")
        other = self.score("Product Development Manager", snippet="snack range for supermarkets")
        self.assertGreater(homes, other + 30)

    def test_off_target_disciplines_drop(self):
        self.assertLess(self.score("Civil Drafter", snippet="roads and stormwater"),
                        self.score("Architectural Drafter"))
        self.assertLess(self.score("Product Manager - SaaS software"), 25)

    def test_location_outside_seq_penalised(self):
        bris = self.score("Building Designer", location="Brisbane QLD")
        syd = self.score("Building Designer", location="Sydney NSW")
        self.assertGreater(bris, syd + 30)

    def test_score_is_clamped(self):
        s = self.score("Archicad Building Designer Drafting Manager",
                       snippet="archicad residential revit volume builder working drawings NCC autocad")
        self.assertLessEqual(s, 100)
        self.assertGreaterEqual(self.score("Barista", location="Perth WA"), 0)


class DedupeTests(unittest.TestCase):
    def test_merges_same_job_across_sources(self):
        a = job("Building Designer", "Coral Homes Pty Ltd", snippet="short")
        b = job("Building designer ", "Coral Homes", snippet="a much longer description")
        b.source = "Other"
        b.salary = "$90k"
        out = bdj.dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].sources, ["Test", "Other"])
        self.assertEqual(out[0].salary, "$90k")
        self.assertEqual(out[0].snippet, "a much longer description")

    def test_mark_new_remembers_between_runs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "seen.json")
            first = [job("Draftsperson"), job("Design Manager")]
            self.assertEqual(bdj.mark_new(first, path), 2)
            second = [job("Draftsperson"), job("BIM Coordinator")]
            self.assertEqual(bdj.mark_new(second, path), 1)
            self.assertFalse(second[0].is_new)
            self.assertTrue(second[1].is_new)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SourceTests(unittest.TestCase):
    def test_adzuna_parsing_and_query_shape(self):
        calls = []
        payload = {"results": [{
            "id": "1", "title": "<strong>Archicad</strong> Draftsperson",
            "company": {"display_name": "Plantation Homes"},
            "location": {"display_name": "Brisbane, Queensland"},
            "redirect_url": "https://www.adzuna.com.au/details/1",
            "created": TODAY.isoformat() + "T01:02:03Z",
            "salary_min": 85000, "salary_max": 95000, "salary_is_predicted": "0",
            "contract_time": "full_time", "description": "Residential documentation &amp; more",
        }]}

        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            return FakeResponse(payload)

        with mock.patch.object(bdj.urllib.request, "urlopen", fake_urlopen), \
                mock.patch.object(bdj, "ADZUNA_MIN_INTERVAL", 0):
            jobs = bdj.search_adzuna("id", "key", ["archicad", "drafter", "building designer"],
                                     "Brisbane", 50, 7, ["civil"], log=lambda m: None)
        self.assertEqual(len(calls), 2)  # single words batched, phrase separate
        q0 = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0]).query)
        q1 = urllib.parse.parse_qs(urllib.parse.urlparse(calls[1]).query)
        self.assertEqual(q0["what_or"], ["archicad drafter"])
        self.assertEqual(q1["what"], ["building designer"])
        self.assertEqual(q0["what_exclude"], ["civil"])
        self.assertEqual(q0["max_days_old"], ["7"])
        j = jobs[0]
        self.assertEqual(j.title, "Archicad Draftsperson")
        self.assertEqual(j.company, "Plantation Homes")
        self.assertEqual(j.salary, "$85k-$95k")
        self.assertEqual(j.posted, TODAY)
        self.assertEqual(j.snippet, "Residential documentation & more")

    def test_jooble_parsing(self):
        payload = {"totalCount": 1, "jobs": [{
            "title": "Building Designer", "company": "Stroud Homes", "location": "Logan QLD",
            "link": "https://au.jooble.org/desc/1", "snippet": "Archicad &nbsp;skills",
            "salary": "$80,000 - $95,000", "source": "seek.com.au", "type": "Full-time",
            "updated": TODAY.isoformat() + "T00:00:00.0000000",
        }]}
        sent = []

        def fake_urlopen(req, timeout=0):
            sent.append(json.loads(req.data.decode()))
            return FakeResponse(payload)

        with mock.patch.object(bdj.urllib.request, "urlopen", fake_urlopen), \
                mock.patch.object(bdj.time, "sleep", lambda s: None):
            jobs = bdj.search_jooble("k", ["building designer"], "Brisbane", 40, 7, log=lambda m: None)
        self.assertEqual(sent[0]["keywords"], "building designer")
        self.assertEqual(jobs[0].company, "Stroud Homes")
        self.assertEqual(jobs[0].posted, TODAY)
        self.assertIn("seek.com.au", jobs[0].source)

    def test_run_search_end_to_end(self):
        payload = {"results": [
            {"title": "Drafting Manager", "company": {"display_name": "Metricon"},
             "location": {"display_name": "Brisbane"}, "redirect_url": "https://a/1",
             "created": TODAY.isoformat(), "description": "volume builder, Archicad"},
            {"title": "Barista", "company": {"display_name": "Cafe"},
             "location": {"display_name": "Brisbane"}, "redirect_url": "https://a/2",
             "created": TODAY.isoformat(), "description": "coffee"},
            {"title": "Old Draftsperson ad", "company": {"display_name": "X"},
             "location": {"display_name": "Brisbane"}, "redirect_url": "https://a/3",
             "created": (TODAY - timedelta(days=40)).isoformat(), "description": ""},
        ]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bdj, "SEEN_PATH", os.path.join(d, "seen.json")), \
                mock.patch.object(bdj.urllib.request, "urlopen", lambda req, timeout=0: FakeResponse(payload)), \
                mock.patch.object(bdj, "ADZUNA_MIN_INTERVAL", 0):
            p = bdj.SearchParams(groups=["Drafting & design management"], days=7, min_score=25)
            jobs = bdj.run_search(p, {"adzuna_app_id": "i", "adzuna_app_key": "k"},
                                  log=lambda m: None, remember=False)
        self.assertEqual([j.title for j in jobs], ["Drafting Manager"])
        self.assertTrue(jobs[0].is_new)


class LinkTests(unittest.TestCase):
    def test_board_urls_encode_query(self):
        urls = dict(bdj.board_search_urls(["archicad", "building designer"], "Brisbane", 7, 50, ["civil"]))
        self.assertTrue(urls["SEEK"].startswith("https://au.seek.com/jobs?"))
        seek_q = urllib.parse.parse_qs(urllib.parse.urlparse(urls["SEEK"]).query)
        self.assertEqual(seek_q["keywords"], ['(archicad OR "building designer") NOT civil'])
        self.assertEqual(seek_q["daterange"], ["7"])
        indeed_q = urllib.parse.parse_qs(urllib.parse.urlparse(urls["Indeed"]).query)
        self.assertEqual(indeed_q["q"], ['(archicad OR "building designer") -civil'])
        self.assertEqual(indeed_q["fromage"], ["7"])
        li_q = urllib.parse.parse_qs(urllib.parse.urlparse(urls["LinkedIn"]).query)
        self.assertEqual(li_q["distance"], ["25"])  # 50 km -> LinkedIn's 25-mile option
        self.assertIn("architectural-drafting/in-All-Brisbane-QLD", urls["SEEK Architectural Drafting"])

    def test_google_query_stays_under_word_limit(self):
        terms = bdj.selected_terms([g["name"] for g in bdj.ROLE_GROUPS])
        urls = dict(bdj.board_search_urls(terms, "Toowoomba", 30, 50, bdj.DEFAULT_EXCLUDE))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(urls["Google Jobs"]).query)["q"][0]
        self.assertLessEqual(len(q.split()), 32)
        self.assertIn("in the last month", q)
        self.assertIn("in-Toowoomba-&-Darling-Downs-QLD", urls["SEEK Architectural Drafting"])

    def test_selected_terms_dedupes_and_adds_custom(self):
        terms = bdj.selected_terms(["Archicad & BIM"], "Archicad, SketchUp")
        self.assertEqual(terms.count("archicad"), 1)
        self.assertIn("SketchUp", terms)


class ExportTests(unittest.TestCase):
    def test_csv_and_html(self):
        j = bdj.score_job(job("Building Designer <b>", snippet="Archicad"), TODAY)
        with tempfile.TemporaryDirectory() as d:
            c, h = os.path.join(d, "a.csv"), os.path.join(d, "a.html")
            bdj.export_csv([j], c)
            bdj.export_html([j], h)
            with open(c, encoding="utf-8-sig") as f:
                self.assertIn("Building Designer", f.read())
            with open(h, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("&lt;b&gt;", text)  # escaped
            self.assertNotIn("Designer <b>", text)


if __name__ == "__main__":
    unittest.main()
