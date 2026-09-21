import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ai_morning_editor.__main__ import reserve_history_folder
from ai_morning_editor.collect import _feed_entries, parse_datetime
from ai_morning_editor.rank import rank_and_dedupe, same_event
from ai_morning_editor import verify
from ai_morning_editor.verify import _primary_candidates
from ai_morning_editor.writer import _parse_json_reply, _valid_selection, write_briefing


class MorningEditorTests(unittest.TestCase):
    def test_feed_parser_enforces_window(self):
        xml = b"""<rss><channel>
        <item><title>OpenAI changes API pricing</title><link>https://example.com/new</link>
        <pubDate>Sun, 13 Sep 2026 10:00:00 GMT</pubDate><description>New enterprise price.</description></item>
        <item><title>Old item</title><link>https://example.com/old</link>
        <pubDate>Thu, 10 Sep 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
        source = {"name": "Official", "url": "https://example.com/feed", "tier": "official"}
        entries = _feed_entries(xml, source, datetime(2026, 9, 12, 12, tzinfo=timezone.utc), now)
        self.assertEqual([item["title"] for item in entries], ["OpenAI changes API pricing"])

    def test_parse_datetime_is_utc(self):
        self.assertEqual(parse_datetime("2026-09-13T08:00:00+08:00").isoformat(), "2026-09-13T00:00:00+00:00")

    def test_duplicate_event_is_merged(self):
        base = {
            "summary": "enterprise business pricing",
            "published_at": "2026-09-13T10:00:00+00:00",
            "source_tier": "media", "collector": "feed",
        }
        first = dict(base, title="Sam Altman says OpenAI going public in 2026 is ill-advised", source_name="A", source_url="https://a.test")
        second = dict(base, title="OpenAI's Sam Altman says it would be ill-advised to go public in 2026", source_name="B", source_url="https://b.test")
        self.assertTrue(same_event(first, second))
        result = rank_and_dedupe([first, second])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["supporting_sources"]), 1)

    def test_official_source_becomes_primary_for_duplicate(self):
        media = {
            "title": "Company launches a new enterprise AI API",
            "summary": "New API pricing for enterprise customers.",
            "published_at": "2026-09-13T10:00:00+00:00", "source_tier": "media",
            "collector": "feed", "source_name": "Media", "source_url": "https://media.test/item",
        }
        official = dict(
            media,
            title="Company launches new enterprise AI API",
            source_tier="official", source_name="Company", source_url="https://company.test/news",
        )
        result = rank_and_dedupe([media, official])
        self.assertEqual(result[0]["source_name"], "Company")
        self.assertEqual(result[0]["supporting_sources"][0]["source_name"], "Media")

    def test_model_cannot_invent_source_index(self):
        candidates = [{"title": str(i)} for i in range(3)]
        payload = {
            "selected": [
                {"candidate_index": i, "title": f"标题{i}", "summary": "事实", "business_impact": "影响"}
                for i in (0, 1, 2, 99)
            ],
            "script": "口播稿",
        }
        selected, script = _valid_selection(payload, candidates, 5)
        self.assertEqual([item["candidate_index"] for item in selected], [0, 1, 2])
        self.assertEqual(script, "口播稿")

    def test_json_reply_accepts_a_preface_and_fenced_object(self):
        payload = _parse_json_reply('说明如下：\n```json\n{"selected": [], "script": "中文"}\n```')
        self.assertEqual(payload["script"], "中文")

    def test_fallback_never_copies_english_feed_text_into_script(self):
        candidates = [{
            "title": f"English API pricing update number {index}",
            "summary": "A long English source summary that must never be copied into Chinese narration.",
            "rank_score": 5.0, "source_name": "Media", "source_url": f"https://example.test/{index}",
            "published_at": "2026-09-13T10:00:00+00:00", "confidence": 0.7,
            "verified": True, "source_tier": "media",
        } for index in range(3)]
        research, script, warnings = write_briefing(candidates, 5, None, use_llm=False)
        self.assertEqual(len(research["stories"]), 3)
        self.assertNotIn("English source summary", script)
        self.assertNotIn("English API pricing", script)
        self.assertIn("不照搬英文原文", script)
        self.assertTrue(warnings)

    def test_media_article_can_trace_a_real_primary_link(self):
        links = [
            ("https://www.anthropic.com/research/alignment-assessment-cybersecurity-incidents", "Anthropic alignment assessment"),
            ("https://unrelated.example/story", "unrelated"),
        ]
        result = _primary_candidates("https://media.test/story", "Anthropic CEO outlines AI safety assessment", links)
        self.assertEqual(result[0]["source_name"], "Anthropic")

    def test_fallback_does_not_pad_with_low_value_candidates(self):
        low = [{
            "title": f"Research update {index}", "summary": "paper benchmark", "rank_score": 0.5,
            "source_name": "Media", "source_url": f"https://example.test/{index}",
            "published_at": "2026-09-13T10:00:00+00:00", "confidence": 0.7,
            "verified": True, "source_tier": "media",
        } for index in range(5)]
        research, script, warnings = write_briefing(low, 5, None, use_llm=False)
        self.assertEqual(research["stories"], [])
        self.assertIn("不为数量凑新闻", script)
        self.assertTrue(warnings)

    def test_same_day_history_uses_a_new_folder_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = reserve_history_folder(root, "2026-09-13", datetime(2026, 9, 13, 18, 0, 0))
            (first / "research.json").write_text("first", encoding="utf-8")
            second = reserve_history_folder(root, "2026-09-13", datetime(2026, 9, 13, 18, 1, 2))
            self.assertNotEqual(first, second)
            self.assertEqual((first / "research.json").read_text(encoding="utf-8"), "first")
            self.assertEqual(second.name, "run-180102")

    def test_confidence_separates_a_thin_note_from_a_full_report(self):
        # Four verified media items used to land on exactly 0.78, so the field
        # carried no information about how much was actually verified.
        def candidate(url, body):
            return {
                "title": "AI safety conversations", "summary": "summary",
                "source_name": "The Verge AI", "source_url": url,
                "published_at": "2026-09-13T10:00:00+00:00", "source_tier": "media",
            }

        class Response:
            def __init__(self, body):
                self.text = f'<script type="application/ld+json">{{"articleBody": "{body}"}}</script>'
                self.headers = {"content-type": "text/html"}
                self.url = "https://example.test/story"
                self.status_code = 200

            def raise_for_status(self):
                return None

        bodies = {
            "https://example.test/thin": "x" * 400,
            "https://example.test/deep": "y" * 4200,
        }
        with patch.object(verify.requests, "Session", lambda: _FakeSession(bodies)):
            verified = verify.verify_candidates([
                candidate("https://example.test/thin", bodies["https://example.test/thin"]),
                candidate("https://example.test/deep", bodies["https://example.test/deep"]),
            ])
        scores = [item["confidence"] for item in verified]
        self.assertTrue(all(item["verified"] for item in verified))
        self.assertNotEqual(scores[0], scores[1], "confidence 必须区分核验深度")
        self.assertLess(scores[0], scores[1])
        self.assertAlmostEqual(scores[0], 0.66 + 0.12 + 0.10 * 400 / 3000, places=2)


class _FakeSession:
    def __init__(self, bodies):
        self.bodies = bodies
        self.headers = {}

    def get(self, url, **kwargs):
        from unittest.mock import Mock

        body = self.bodies.get(url, "z" * 300)
        response = Mock()
        response.text = f'<script type="application/ld+json">{{"articleBody": "{body}"}}</script>'
        response.headers = {"content-type": "text/html"}
        response.url = url
        response.status_code = 200
        response.raise_for_status.return_value = None
        return response


if __name__ == "__main__":
    unittest.main()
