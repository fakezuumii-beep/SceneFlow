import json
import tempfile
import unittest
from pathlib import Path

from ai_morning_editor import motion_plan


# The SRT time separator is assembled at runtime so this source file never
# carries a literal diff marker.
ARROW = chr(45) * 2 + chr(62)


def srt(*rows):
    blocks = []
    for index, (start, end, text) in enumerate(rows, 1):
        blocks.append(f"{index}\n{start} {ARROW} {end}\n{text}\n")
    return "\n".join(blocks)


SRT_SAMPLE = srt(
    ("00:00:00,000", "00:00:04,000", "今天最值得关注的一件事。"),
    ("00:00:04,000", "00:00:12,500", "MRH Trowe 把 AI 智能体推到全员生产环境。"),
    ("00:00:12,500", "00:00:20,000", "首月单座席成本大约 14 美元。"),
    ("00:00:20,000", "00:00:30,000", "AWS 开源了 38 个医疗智能体技能。"),
    ("00:00:30,000", "00:00:42,000", "Google 开放了 Home MCP 服务器早期访问。"),
)

STORIES = [
    {
        "title": "MRH Trowe 让 400 名员工用上自服务 AI 智能体",
        "summary": "首月单座席成本约 14 美元，覆盖 400 名员工。",
        "business_impact": "门槛不是模型能力，而是身份认证、数据驻留、审计和成本透明。机会是预算有参照，风险是厂商自述。",
        "source_name": "AWS ML Blog",
        "source_url": "https://example.com/a",
        "confidence": 0.88,
        "verified": True,
    },
    {
        "title": "AWS 开源 38 个医疗智能体技能",
        "summary": "覆盖基因组学、药物发现、理赔运营、医学影像等 11 个领域。",
        "business_impact": "降低医疗 AI 公司自建推理流程的成本，但评测由发布方自评。",
        "source_name": "AWS ML Blog",
        "source_url": "https://example.com/b",
        "confidence": 0.7,
        "verified": True,
    },
    {
        "title": "Google 开放 Home MCP 服务器早期访问",
        "summary": "面向美国每月 20 美元的订阅用户逐步开放。",
        "business_impact": "入口从官方 App 让渡给第三方智能体，风险在权限与隐私。",
        "source_name": "TechCrunch AI",
        "source_url": "https://example.com/c",
        "confidence": 0.78,
        "verified": True,
    },
]


class MorningMotionPlanTests(unittest.TestCase):
    def test_parse_srt_reads_arrow_and_timestamps(self):
        cues = motion_plan.parse_srt(SRT_SAMPLE)
        self.assertEqual(len(cues), 5)
        self.assertAlmostEqual(cues[0]["start"], 0.0, places=3)
        self.assertAlmostEqual(cues[-1]["end"], 42.0, places=3)
        self.assertIn("MRH Trowe", cues[1]["text"])
        self.assertEqual(motion_plan.parse_srt("not an srt"), [])

    def test_extract_numbers_keeps_unit_and_order(self):
        found = motion_plan.extract_numbers("首月 14 美元", "覆盖 400 名员工与 40% 降本")
        self.assertEqual([item["value"] for item in found], ["14美元", "400名", "40%"])
        self.assertEqual(found[0]["unit"], "美元")

    def test_jitter_range_is_ordered_and_bounded(self):
        low, high = motion_plan.jitter_range(14, "美元")
        self.assertLess(low, high)
        self.assertGreaterEqual(low, 1)
        ten, top = motion_plan.jitter_range(40, "%")
        self.assertLessEqual(top, 100)

    def test_format_title_splits_and_accents_contrast(self):
        self.assertEqual(motion_plan.format_title("门槛：不是模型能力"), "门槛|*不是模型能力*")
        plain = motion_plan.format_title("成本出现新变化")
        self.assertNotIn("*", plain)

    def test_enumerable_items_needs_a_real_list(self):
        self.assertEqual(
            motion_plan.enumerable_items("身份认证、数据驻留、审计、成本透明"),
            ["身份认证", "数据驻留", "审计", "成本透明"],
        )
        self.assertEqual(motion_plan.enumerable_items("只有一句话没有列举"), [])

    def test_story_board_specs_are_deterministic(self):
        first = motion_plan.story_board_specs(STORIES[0], 0, 3)
        second = motion_plan.story_board_specs(STORIES[0], 0, 3)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["template"], "M_TITLE")
        self.assertTrue(any(spec["template"] == "M_NUMBER" for spec in first))
        for spec in first:
            self.assertIn("template", spec["props"])
            self.assertEqual(spec["template"], spec["props"]["template"])

    def test_align_stories_snaps_onto_real_cues(self):
        cues = motion_plan.parse_srt(SRT_SAMPLE)
        spans, warnings = motion_plan.align_stories(cues, STORIES, "")
        self.assertEqual(warnings, [])
        self.assertEqual(len(spans), 3)
        for (start, end), following in zip(spans, spans[1:]):
            self.assertLess(start, end)
            self.assertAlmostEqual(end, following[0], places=3)

    def test_build_plan_tiles_the_narration_without_gaps(self):
        plan = motion_plan.build_plan(
            {"date": "2026-09-18", "stories": STORIES}, "口播稿", SRT_SAMPLE
        )
        self.assertEqual(plan["style"], "intel_board")
        self.assertEqual(plan["timeline_source"], "srt")
        self.assertEqual(plan["warnings"], [])
        boards = plan["boards"]
        self.assertGreaterEqual(plan["board_count"], len(STORIES) + 2)
        self.assertAlmostEqual(boards[0]["start"], 0.0, places=3)
        self.assertAlmostEqual(boards[-1]["end"], 42.0, places=3)
        for current, following in zip(boards, boards[1:]):
            self.assertAlmostEqual(current["end"], following["start"], places=2)
            self.assertGreaterEqual(current["duration"], motion_plan.MIN_BOARD_SECONDS)
        self.assertEqual([b["id"] for b in boards[:2]], ["B000", "B001-1"])
        self.assertEqual(boards[-1]["id"], "B900")

    def test_build_plan_falls_back_with_a_warning(self):
        stories = [dict(story, title="完全对不上的标题ZZZ") for story in STORIES]
        plan = motion_plan.build_plan({"date": "x", "stories": stories}, "口播稿", SRT_SAMPLE)
        self.assertEqual(plan["timeline_source"], "estimate")
        self.assertTrue(any("对齐" in warning for warning in plan["warnings"]))

    def test_empty_research_still_produces_one_board(self):
        plan = motion_plan.build_plan({"date": "x", "stories": []}, "", None)
        self.assertEqual(plan["board_count"], 1)
        self.assertEqual(plan["boards"][0]["props"]["template"], "M_TITLE")

    def test_to_shots_marks_every_board_as_intel_board(self):
        plan = motion_plan.build_plan({"date": "x", "stories": STORIES}, "", SRT_SAMPLE)
        shots = motion_plan.to_shots(plan)
        self.assertEqual(len(shots), plan["board_count"])
        for shot in shots:
            self.assertEqual(shot["visual_role"], "M")
            self.assertEqual(shot["motion_style"], "intel_board")
            self.assertEqual(shot["motion_data"]["template"], shot["motion_type"])

    def test_write_plan_and_render_plan_smoke(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            research = {"date": "2026-09-18", "stories": STORIES[:1]}
            plan = motion_plan.write_plan(folder, research, "口播稿", SRT_SAMPLE)
            saved = json.loads((folder / "motion-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["board_count"], plan["board_count"])

            single = {"style": "intel_board", "boards": [plan["boards"][0]]}
            rendered = motion_plan.render_plan(single, folder / "clips", (320, 320))
            self.assertEqual(len(rendered), 1)
            clip = Path(rendered[0]["clip"])
            self.assertTrue(clip.is_file())
            self.assertGreater(clip.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
