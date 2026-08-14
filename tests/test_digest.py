
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

import starlink_daily_digest as digest
from starlink_utils import looks_starlink_critical


class TestRecall(unittest.TestCase):
    """Regressions for the items the filter used to drop on the floor."""

    def test_keeps_starlink_headlines_that_mention_other_programs(self):
        cases = [
            ("Starlink satellites deorbit near the ISS, operators warn",
             "Close approaches logged.", ""),
            ("Starlink debris study published as Falcon 9 cadence climbs",
             "Researchers measured alumina.", ""),
            ("Starlink reentries raise ozone concerns, scientists say",
             "New paper in GRL.", ""),
        ]
        for title, summary, link in cases:
            with self.subTest(title=title):
                self.assertTrue(looks_starlink_critical(title, summary, link))

    def test_still_drops_stories_about_other_programs(self):
        self.assertFalse(looks_starlink_critical(
            "Artemis II crew prepares for launch",
            "Unrelated to Starlink outage history.", ""))

    def test_keeps_regulatory_and_legal_coverage(self):
        cases = [
            ("Lawsuit filed over Starlink ground station", "Court documents.", ""),
            ("FCC opens proceeding on Starlink spectrum", "Filing published.", ""),
            ("Scientists warn about Starlink impact on dark skies", "New study.", ""),
        ]
        for title, summary, link in cases:
            with self.subTest(title=title):
                self.assertTrue(looks_starlink_critical(title, summary, link))

    def test_marketing_is_still_rejected(self):
        self.assertFalse(looks_starlink_critical(
            "Starlink expands to new country", "Service now available.", ""))


class TestDedupe(unittest.TestCase):
    def test_same_story_from_two_feeds_collapses(self):
        items = [
            {"title": "Starlink reentry study published - Reuters",
             "link": "https://news.google.com/x", "source": "News", "summary": "", "date": "2"},
            {"title": "Starlink reentry study published",
             "link": "https://spacenews.com/y", "source": "SpaceNews", "summary": "", "date": "1"},
        ]
        self.assertEqual(len(digest.dedupe_items(items)), 1)

    def test_identical_links_collapse(self):
        items = [
            {"title": "One headline", "link": "https://a/b", "source": "A", "summary": "", "date": "2"},
            {"title": "Another headline entirely", "link": "https://a/b", "source": "B", "summary": "", "date": "1"},
        ]
        self.assertEqual(len(digest.dedupe_items(items)), 1)

    def test_distinct_stories_are_kept(self):
        items = [
            {"title": "Starlink outage in Europe", "link": "https://a/1", "source": "A", "summary": "", "date": "2"},
            {"title": "Starlink debris over Canada", "link": "https://a/2", "source": "A", "summary": "", "date": "1"},
        ]
        self.assertEqual(len(digest.dedupe_items(items)), 2)


class TestBucketing(unittest.TestCase):
    def item(self, title, summary=""):
        return {"title": title, "summary": summary, "link": f"https://x/{hash(title)}",
                "source": "test", "date": "2026-08-01T00:00:00"}

    def test_unclassifiable_items_land_in_the_fallback_domain(self):
        items = [self.item("Starlink licence revoked after court filing")]
        with mock.patch.object(digest, "load_seen", return_value=[]), \
             mock.patch.object(digest, "save_seen"):
            data = digest.build_digest_data(items)
        self.assertTrue(data["regulatory_update"])
        self.assertEqual(len(data["archive_regulatory"]), 1)

    def test_topic_items_still_reach_their_domain(self):
        items = [self.item("Starlink reentry alumina in the stratosphere")]
        with mock.patch.object(digest, "load_seen", return_value=[]), \
             mock.patch.object(digest, "save_seen"):
            data = digest.build_digest_data(items)
        self.assertTrue(data["environmental_update"])
        self.assertFalse(data["regulatory_update"])

    def test_markdown_carries_every_domain_section_and_archive(self):
        with mock.patch.object(digest, "load_seen", return_value=[]), \
             mock.patch.object(digest, "save_seen"):
            data = digest.build_digest_data([self.item("Starlink debris event")])
        md = digest.format_digest_markdown(data)
        for name in digest.DOMAINS:
            self.assertIn(f"### {name}", md)
            self.assertIn(f"**Archive — {name}**", md)
            self.assertRegex(md, rf"\| {name} \| (Yes|No) \|")

    def test_archive_regex_isolates_each_domain_block(self):
        with mock.patch.object(digest, "load_seen", return_value=[]), \
             mock.patch.object(digest, "save_seen"):
            data = digest.build_digest_data([
                self.item("Starlink debris event"),
                self.item("Starlink licence revoked after court filing"),
            ])
        md = digest.format_digest_markdown(data)
        import re
        env = re.search(digest.RX_ARCHIVE["Environmental"], md, re.I).group(2)
        self.assertIn("debris event", env)
        self.assertNotIn("licence revoked", env)


class TestSeenFile(unittest.TestCase):
    def test_cap_keeps_the_most_recent_keys(self):
        keys = [f"https://example.com/{i:05d}" for i in range(digest.SEEN_CAP + 50)]
        with mock.patch.object(digest, "SEEN_FILE") as seen_file:
            digest.save_seen(keys)
            written = json.loads(seen_file.write_text.call_args[0][0])
        self.assertEqual(len(written), digest.SEEN_CAP)
        self.assertEqual(written[-1], keys[-1])   # newest survives


class TestFeedHealth(unittest.TestCase):
    def test_health_summarises_status_counts(self):
        health = [
            {"name": "A", "status": "ok", "entries": 30, "recent": 12, "matched": 3, "detail": ""},
            {"name": "B", "status": "error", "entries": 0, "recent": 0, "matched": 0, "detail": "timeout"},
            {"name": "C", "status": "empty", "entries": 0, "recent": 0, "matched": 0, "detail": ""},
        ]
        with mock.patch.object(digest, "FEED_HEALTH_FILE") as health_file:
            digest.write_feed_health(health, kept=3)
            payload = json.loads(health_file.write_text.call_args[0][0])
        self.assertEqual(payload["feeds_configured"], 3)
        self.assertEqual(payload["feeds_ok"], 1)
        self.assertEqual(payload["feeds_failed"], 1)
        self.assertEqual(payload["feeds_empty"], 1)
        self.assertEqual(payload["items_matched"], 3)
        self.assertEqual(payload["items_kept"], 3)
        self.assertEqual(payload["feeds"][0]["name"], "A")   # best yield first


if __name__ == "__main__":
    unittest.main()
