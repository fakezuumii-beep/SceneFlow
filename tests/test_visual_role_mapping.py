import unittest

import core
from visual_director.master_plan import (
    LEGACY_ROLE_MAPPING_VERSION,
    from_shots,
    infer_visual_role,
    normalize_project,
)


def shot(**kwargs):
    base = {"id": "s1", "kind": "B", "start": 0.0, "end": 4.0, "text": "一句话。"}
    base.update(kwargs)
    return base


def project_with(shots, plan=None):
    return {
        "id": "p1",
        "duration": sum(float(s["end"]) - float(s["start"]) for s in shots),
        "video_profile": "general",
        "shots": shots,
        "visual_master_plan": plan,
    }


class LegacyRoleMappingTests(unittest.TestCase):
    def test_accepted_plans_keep_the_old_ab_only_behaviour(self):
        # Without the extended flag a data shot stays B-roll, which is what
        # every already-reviewed episode was built with.
        self.assertEqual(infer_visual_role(shot(semantic_type="data")), "B")
        self.assertEqual(
            infer_visual_role(shot(text="首月单座席成本 14 美元")), "B"
        )

    def test_extended_roles_promote_explicit_motion_type(self):
        role = infer_visual_role(
            shot(motion_type="M_NUMBER"), allow_extended_roles=True
        )
        self.assertEqual(role, "M")

    def test_extended_roles_promote_data_semantics(self):
        role = infer_visual_role(
            shot(semantic_type="data", text="覆盖 400 名员工。"),
            allow_extended_roles=True,
        )
        self.assertEqual(role, "M")

    def test_extended_roles_promote_a_unit_bearing_figure(self):
        role = infer_visual_role(
            shot(text="首月单座席成本大约 14 美元。"), allow_extended_roles=True
        )
        self.assertEqual(role, "M")

    def test_extended_roles_ignore_a_bare_number(self):
        # A year or a list index inside an ordinary sentence is not a data
        # board; promoting those would flood the plan with motion segments.
        role = infer_visual_role(
            shot(text="这个判断在 2026 年可能发生变化。"), allow_extended_roles=True
        )
        self.assertEqual(role, "B")

    def test_extended_roles_do_not_invent_new_host_or_evidence_work(self):
        self.assertEqual(
            infer_visual_role(
                shot(semantic_type="opinion", visual_subject="某公司"),
                allow_extended_roles=True,
            ),
            "B",
        )
        self.assertEqual(
            infer_visual_role(
                shot(text="打开官网查看入口。"), allow_extended_roles=True
            ),
            "B",
        )

    def test_explicit_roles_and_host_kind_are_never_overridden(self):
        for extended in (False, True):
            self.assertEqual(
                infer_visual_role(shot(visual_role="E"), allow_extended_roles=extended),
                "E",
            )
            self.assertEqual(
                infer_visual_role(
                    {"kind": "A", "text": "今天聊一件事"}, allow_extended_roles=extended
                ),
                "A",
            )

    def test_a_stored_v2_plan_is_left_untouched(self):
        plan = {
            "schema_version": "sceneflow-visual-master-plan-v1",
            "source": "legacy-project",
            "legacy_role_mapping_version": 2,
            "segments": [{
                "id": "S001", "visual_role": "B", "legacy_roll_type": "B",
                "semantic_type": "data", "start": 0.0, "end": 4.0,
            }],
        }
        project = project_with(
            [shot(visual_segment_id="S001", visual_role="B", semantic_type="data")],
            plan,
        )
        normalize_project(project)
        self.assertEqual(project["visual_master_plan"]["legacy_role_mapping_version"], 2)
        self.assertEqual(project["visual_master_plan"]["segments"][0]["visual_role"], "B")
        self.assertEqual(project["shots"][0]["visual_role"], "B")

    def test_the_planning_path_keeps_motion_and_stamps_the_new_version(self):
        project = project_with([
            shot(id="s1", visual_segment_id="S001", semantic_type="data",
                 text="首月单座席成本大约 14 美元。"),
            shot(id="s2", visual_segment_id="S002", semantic_type="event",
                 text="这家公司做商业和工业保险。"),
        ])
        plan = from_shots(project, None, allow_extended_roles=True)
        self.assertEqual(plan["legacy_role_mapping_version"], LEGACY_ROLE_MAPPING_VERSION)
        roles = {segment["id"]: segment["visual_role"] for segment in plan["segments"]}
        self.assertEqual(roles["S001"], "M")
        self.assertEqual(roles["S002"], "B")
        # A motion segment still renders through the legacy B-roll slot.
        self.assertEqual(plan["segments"][0]["legacy_roll_type"], "B")

    def test_a_lazy_backfill_and_structural_edits_stay_on_the_ab_mapping(self):
        # normalize_project and rebuild_after_structural_edit both rebuild with
        # the default, so merely loading or splitting a shot never changes an
        # existing episode's roles.
        project = project_with([
            shot(id="s1", visual_segment_id="S001", semantic_type="data",
                 text="首月单座席成本大约 14 美元。"),
        ])
        normalize_project(project)
        plan = project["visual_master_plan"]
        self.assertEqual(plan["legacy_role_mapping_version"], 2)
        self.assertEqual(plan["segments"][0]["visual_role"], "B")

        rebuilt = from_shots(project, None)
        self.assertEqual(rebuilt["legacy_role_mapping_version"], 2)
        self.assertEqual(rebuilt["segments"][0]["visual_role"], "B")


class MotionStyleOptionTests(unittest.TestCase):
    def test_default_motion_style_stays_on_the_original_templates(self):
        self.assertEqual(core.DEFAULT_PROJECT_OPTIONS["motion_style"], "scene_flow")

    def test_options_normalization_backfills_the_new_key(self):
        project = {"options": {"broll_ratio": 60}}
        self.assertTrue(core.normalize_project_options(project))
        self.assertEqual(project["options"]["motion_style"], "scene_flow")

    def test_inherited_defaults_reset_motion_style(self):
        source = {"options": {"motion_style": "intel_board", "broll_ratio": 40}}
        project = {"id": "p2", "options": {}}
        core._inherit_project_defaults(project, source)
        self.assertEqual(project["options"]["motion_style"], "scene_flow")
        self.assertEqual(project["options"]["broll_ratio"], 40)


if __name__ == "__main__":
    unittest.main()
