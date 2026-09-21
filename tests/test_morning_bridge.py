import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core
import morning_bridge


class MorningBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "ai_morning_editor" / "output"
        self.history = self.root / "ai_morning_editor" / "history"
        self.snapshot = self.history / "2026-09-13"
        self.output.mkdir(parents=True)
        self.snapshot.mkdir(parents=True)
        self.research = {
            "date": "2026-09-13", "generated_at": "2026-09-13T18:00:00+08:00",
            "window_start": "2026-09-12T10:00:00+00:00", "window_end": "2026-09-13T10:00:00+00:00",
            "history_path": "ai_morning_editor/history/2026-09-13",
            "stories": [{
                "title": "企业 AI API 降价", "summary": "公司发布新价格。", "business_impact": "企业调用成本下降。",
                "source_name": "Media", "source_url": "https://media.example/story",
                "published_at": "2026-09-13T09:00:00+00:00", "confidence": 0.9, "verified": True,
                "media_source": {"source_name": "Media", "source_url": "https://media.example/story", "verified": True},
                "primary_source": {"source_name": "Company", "source_url": "https://company.example/news", "verified": True},
            }],
        }
        self.script = "今天最值得关注的是企业 AI API 降价。"
        text = json.dumps(self.research, ensure_ascii=False)
        for folder in (self.output, self.snapshot):
            (folder / "research.json").write_text(text, encoding="utf-8")
            (folder / "script.md").write_text(self.script, encoding="utf-8")
        self.patches = [
            patch.object(morning_bridge, "ROOT", self.root),
            patch.object(morning_bridge, "OUTPUT", self.output),
            patch.object(morning_bridge, "HISTORY", self.history),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_reads_sources_and_script_without_copy_paste(self):
        result = morning_bridge.read_current()
        self.assertTrue(result["ready"])
        self.assertEqual(result["stories"][0]["primary_source"]["source_name"], "Company")
        self.assertEqual(result["script"], self.script)

    def test_rejects_an_english_heavy_briefing(self):
        english = "This is an English feed summary copied directly into the morning briefing. " * 8
        for folder in (self.output, self.snapshot):
            data = json.loads((folder / "research.json").read_text(encoding="utf-8"))
            data["stories"][0]["summary"] = english
            (folder / "research.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            (folder / "script.md").write_text("今天关注。" + english, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "过多英文"):
            morning_bridge.read_current()

    def test_accepts_a_brand_only_title(self):
        # Product and company names are allowed to stay in their original form,
        # so a title can be mostly latin without being a pasted English source.
        for folder in (self.output, self.snapshot):
            data = json.loads((folder / "research.json").read_text(encoding="utf-8"))
            data["stories"][0]["title"] = "Moonshot AI 的 Kimi K3 上线 Amazon Bedrock"
            (folder / "research.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        result = morning_bridge.read_current()
        self.assertTrue(result["ready"])
        self.assertEqual(
            result["stories"][0]["title"],
            "Moonshot AI 的 Kimi K3 上线 Amazon Bedrock",
        )

    def test_rejects_a_title_with_no_chinese_at_all(self):
        for folder in (self.output, self.snapshot):
            data = json.loads((folder / "research.json").read_text(encoding="utf-8"))
            data["stories"][0]["title"] = "Moonshot AI launches Kimi K3 on Amazon Bedrock"
            (folder / "research.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        with self.assertRaisesRegex(ValueError, "过多英文"):
            morning_bridge.read_current()

    def test_confirm_creates_one_idempotent_sceneflow_project(self):
        projects = self.root / "projects"
        projects.mkdir()
        current = morning_bridge.read_current()
        with patch.object(core, "PROJECTS", projects):
            first, reused = morning_bridge.import_project(core, current["generation_id"])
            second, reused_second = morning_bridge.import_project(core, current["generation_id"])
        self.assertFalse(reused)
        self.assertTrue(reused_second)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["script"]["text"], self.script)
        self.assertEqual(first["morning_briefing"]["history_path"], self.research["history_path"])
        # The briefing opts into the animated intel boards; other episodes keep
        # the default static-still templates.
        self.assertEqual(first["options"]["motion_style"], "intel_board")

    def test_final_video_is_copied_without_overwriting_history(self):
        video = self.root / "video.mp4"
        video.write_bytes(b"first video")
        project = {"morning_briefing": {"history_path": self.research["history_path"]}}
        first = morning_bridge.archive_final(project, video, "export-a")
        self.assertEqual(first, "ai_morning_editor/history/2026-09-13/final.mp4")
        video.write_bytes(b"second video")
        second = morning_bridge.archive_final(project, video, "export-b")
        self.assertTrue(second.endswith("final-export-b.mp4"))
        self.assertEqual((self.snapshot / "final.mp4").read_bytes(), b"first video")

    def test_draft_export_is_not_archived_as_the_episode_final(self):
        # A draft can still carry A-roll placeholders, so archiving it first
        # left final.mp4 pointing at an unfinished cut all day.
        video = self.root / "draft.mp4"
        video.write_bytes(b"draft with placeholders")
        project = {"morning_briefing": {"history_path": self.research["history_path"]}}
        self.assertIsNone(morning_bridge.archive_final(project, video, "export-draft", "draft"))
        self.assertFalse((self.snapshot / "final.mp4").exists())
        video.write_bytes(b"real final")
        archived = morning_bridge.archive_final(project, video, "export-final", "final")
        self.assertEqual(archived, "ai_morning_editor/history/2026-09-13/final.mp4")
        self.assertEqual((self.snapshot / "final.mp4").read_bytes(), b"real final")


if __name__ == "__main__":
    unittest.main()
