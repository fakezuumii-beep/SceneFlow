import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

import core
from motion import intel_board
from motion.template_router import (
    DEFAULT_MOTION_STYLE,
    MOTION_STYLES,
    build_motion_plan,
    normalize_motion_style,
)


PROPS = {
    'template': 'M_NUMBER',
    'eyebrow': {'left': '09.18', 'center': 'AI 商业晨报', 'right': '第一条'},
    'title': '智能体真正进了|*生产*环境',
    'subtitle': 'MRH Trowe ｜ 德国商业与工业保险经纪商',
    'numbers': [
        {'value': '400', 'label': '名员工', 'jitter': [120, 999]},
        {'value': '14', 'label': '美元 · 每座席 · 首月', 'accent': True, 'jitter': [3, 89]},
    ],
    'tags': ['Strands Agents', 'LibreChat'],
}


def diff_ratio(left, right):
    difference = ImageChops.difference(left.convert('RGB'), right.convert('RGB'))
    return ImageStat.Stat(difference.convert('L')).mean[0] / 255


class IntelBoardTests(unittest.TestCase):
    def test_motion_style_normalization_defaults_to_scene_flow(self):
        self.assertEqual(normalize_motion_style(None), DEFAULT_MOTION_STYLE)
        self.assertEqual(normalize_motion_style(''), DEFAULT_MOTION_STYLE)
        self.assertEqual(normalize_motion_style('unknown'), DEFAULT_MOTION_STYLE)
        self.assertEqual(normalize_motion_style('INTEL_BOARD'), 'intel_board')
        self.assertEqual(set(MOTION_STYLES), {'scene_flow', 'intel_board'})

    def test_build_motion_plan_carries_style_without_changing_template(self):
        segment = {'motion_type': 'M_NUMBER', 'text': '首月单座席成本 14 美元',
                   'visual_subject': '成本锚点'}
        legacy = build_motion_plan(segment, 9, '9:16')
        self.assertEqual(legacy['template'], 'M_NUMBER')
        self.assertEqual(legacy['style'], 'scene_flow')
        self.assertIn('scene_flow', legacy['composition_id'])

        styled = build_motion_plan(segment, 9, '9:16', 'intel_board')
        self.assertEqual(styled['template'], 'M_NUMBER')
        self.assertEqual(styled['style'], 'intel_board')
        self.assertIn('intel_board', styled['composition_id'])
        self.assertEqual(styled['props']['aspect_ratio'], '9:16')

    def test_title_parser_marks_accent_runs_and_line_breaks(self):
        runs = intel_board.parse_title('智能体真正进了|*生产*环境')
        self.assertEqual(runs[0], [('智能体真正进了', False)])
        self.assertEqual(runs[1], [('生产', True), ('环境', False)])
        self.assertEqual(intel_board.parse_title(''), [[('重点信息', False)]])

    def test_easing_and_progress_are_bounded(self):
        self.assertEqual(intel_board.ease_out(-1), 0)
        self.assertEqual(intel_board.ease_out(2), 1)
        self.assertEqual(intel_board.segment(0.5, 1, 0), 1)
        self.assertEqual(intel_board.segment(0.25, 0, 1), 0.25)
        self.assertEqual(intel_board.segment(2, 0, 1), 1)

    def test_wrap_text_keeps_lines_inside_the_measure(self):
        draw = ImageDraw.Draw(Image.new('RGB', (10, 10)))
        fnt = intel_board._font(24)
        long_copy = '这是把智能体从试点推向全员生产的一个可量化样本，说明受监管行业也能在合规框架内做自服务。'
        lines = intel_board.wrap_text(draw, long_copy, fnt, 240, max_lines=3)
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertLessEqual(draw.textlength(line, font=fnt), 240)
        self.assertTrue(lines[-1].endswith('…'))
        self.assertEqual(intel_board.wrap_text(draw, '', fnt, 240), [])

    def test_compare_panels_do_not_overflow_their_column(self):
        props = dict(PROPS, template='M_COMPARE', axis='columns', accent_side=1, columns=[
            {'heading': '可能的机会',
             'body': '这是把智能体从试点推向全员生产的一个可量化样本，说明受监管行业也能做自服务。'},
            {'heading': '需要留意',
             'body': '真正的门槛不是模型能力，而是身份认证、数据驻留、审计和成本透明这几件事。',
             'callouts': ['单座席成本来自厂商自述', '长期成本还要看使用强度']},
        ])
        board = intel_board.Board(720, 1280, props)
        paper = intel_board.make_paper(720, 1280)
        frame = intel_board.render_frame(board, paper, 1.0)
        self.assertEqual(frame.size, (720, 1280))

    def test_generic_router_props_still_draw_the_compare_panels(self):
        # build_motion_plan emits the scene_flow prop set (before / after /
        # label), never the intel-board columns key. Without the adapter the
        # board rendered as a title on an otherwise empty frame.
        segment = {
            'motion_type': 'M_COMPARE',
            'visual_subject': '两种监管路径的对比：不设强制标准 vs 国会推进框架',
            'text': '如果美国最终不设强制标准，头部实验室的自主权更大。',
            'motion_data': {
                'before': '不设强制标准：头部自主权更大，企业缺少统一安全背书',
                'after': '国会推进框架：合规成竞争壁垒，中小玩家成本上升',
                'label': '监管路径对比',
            },
        }
        plan = build_motion_plan(segment, 17.4, '9:16', 'intel_board')
        self.assertNotIn('columns', plan['props'])
        props = dict(plan['props'], template='M_COMPARE')
        board = intel_board.Board(720, 1280, props)
        paper = intel_board.make_paper(720, 1280)
        frame = intel_board.render_frame(board, paper, 1.0)
        body = (0, int(1280 * 0.38), 720, int(1280 * 0.74))
        self.assertGreater(
            diff_ratio(frame.crop(body), paper.crop(body)), 0.01,
            'M_COMPARE 必须在标题下方画出对比栏，不能只剩标题',
        )
        columns = intel_board.normalize_props(props)['columns']
        self.assertEqual([column['heading'] for column in columns],
                         ['不设强制标准', '国会推进框架'])
        self.assertEqual(columns[1]['body'], '合规成竞争壁垒，中小玩家成本上升')

    def test_plain_string_numbers_do_not_crash_the_number_board(self):
        board = intel_board.Board(360, 640, {
            'template': 'M_NUMBER', 'title': '成本锚点',
            'numbers': ['14 美元', '400 名员工'],
        })
        frame = intel_board.render_frame(board, intel_board.make_paper(360, 640), 1.0)
        self.assertEqual(frame.size, (360, 640))

    def test_split_board_keeps_one_build_clock_instead_of_restarting(self):
        # Board.duration is the part, build_offset is where the part starts
        # inside the whole board: the next part must resume, not restart.
        first = intel_board.Board(360, 640, dict(
            PROPS, duration=3.3, build_seconds=10.8, build_offset=0.0))
        second = intel_board.Board(360, 640, dict(
            PROPS, duration=6.4, build_seconds=10.8, build_offset=3.3))
        self.assertAlmostEqual(first.build_progress(0.0), 0.0, places=3)
        self.assertAlmostEqual(first.build_progress(1.0), 3.3 / 10.8, places=3)
        self.assertAlmostEqual(second.build_progress(0.0), first.build_progress(1.0), places=3)
        self.assertGreater(second.build_progress(1.0), first.build_progress(1.0))

    def test_short_part_still_finishes_its_build(self):
        # A part shorter than MIN_BUILD_SECONDS used to stop at half a board,
        # so the data layer of a split board never appeared on screen.
        with tempfile.TemporaryDirectory() as folder:
            clip = Path(folder) / 'motion.mp4'
            shot = {'id': 'q02', 'start': 0.0, 'end': 3.3, 'motion_type': 'M_COMPARE',
                    'motion_style': 'intel_board', 'duration': 17.4,
                    'motion_data': {'duration': 17.4, 'template': 'M_COMPARE',
                                    'title': '两种监管路径的对比',
                                    'before': '不设强制标准：企业缺少统一安全背书',
                                    'after': '国会推进框架：合规成竞争壁垒'}}
            rendered, still = intel_board.render_intel_board_clip(shot, (320, 320), clip)
            self.assertTrue(rendered.is_file())
            board = intel_board.Board(320, 320, dict(
                shot['motion_data'], build_seconds=10.8, build_offset=0.0))
            board.duration = 3.3
            self.assertAlmostEqual(board.build_progress(1.0), 3.3 / 10.8, places=3)

    def test_router_shares_one_board_clock_across_split_parts(self):
        from visual_director.router import apply_routes
        project = {
            'options': {'aspect_ratio': '9:16', 'motion_style': 'intel_board'},
            'visual_master_plan': {'segments': [{
                'id': 'S001', 'visual_role': 'M', 'motion_type': 'M_COMPARE',
                'text': '两种路径的对比。', 'duration': 10, 'start': 0, 'end': 10,
            }]},
            'shots': [
                {'id': 'm1', 'visual_segment_id': 'S001', 'start': 0.0, 'end': 4.0},
                {'id': 'm2', 'visual_segment_id': 'S001', 'start': 4.0, 'end': 10.0},
            ],
        }
        apply_routes(project)
        first, second = project['shots']
        self.assertEqual(first['motion_plan']['props']['build_offset'], 0.0)
        self.assertEqual(second['motion_plan']['props']['build_offset'], 4.0)
        self.assertEqual(first['motion_plan']['props']['duration'], 10.0)

    def test_board_frames_change_over_time(self):
        board = intel_board.Board(360, 640, PROPS)
        paper = intel_board.make_paper(360, 640)
        early = intel_board.render_frame(board, paper, 0.05)
        middle = intel_board.render_frame(board, paper, 0.55)
        final = intel_board.render_frame(board, paper, 1.0)
        self.assertGreater(diff_ratio(early, middle), 0.01)
        self.assertGreater(diff_ratio(middle, final), 0.001)

    def test_final_frame_is_stable_after_the_close(self):
        board = intel_board.Board(360, 640, PROPS)
        paper = intel_board.make_paper(360, 640)
        settled = intel_board.render_frame(board, paper, 0.90)
        final = intel_board.render_frame(board, paper, 1.0)
        self.assertLess(diff_ratio(settled, final), 0.0005)

    def test_long_board_builds_early_then_holds(self):
        # A board covering a long stretch of narration must finish its build
        # inside the build window and hold the settled frame afterwards.
        board = intel_board.Board(360, 640, dict(PROPS, duration=24.0, build_seconds=8.0))
        paper = intel_board.make_paper(360, 640)
        self.assertAlmostEqual(board.build_progress(0.0), 0.0, places=3)
        self.assertAlmostEqual(board.build_progress(1 / 3), 1.0, places=3)
        held_early = intel_board.render_frame(board, paper, 0.5)
        held_late = intel_board.render_frame(board, paper, 1.0)
        self.assertLess(diff_ratio(held_early, held_late), 0.0005)
        self.assertGreater(diff_ratio(intel_board.render_frame(board, paper, 0.05), held_late), 0.01)

    def test_clip_render_emits_moving_video_and_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            clip = Path(folder) / 'motion.mp4'
            shot = {'id': 'q01', 'start': 0.0, 'end': 1.4, 'motion_type': 'M_NUMBER',
                    'motion_style': 'intel_board', 'motion_data': PROPS}
            rendered, still = intel_board.render_intel_board_clip(shot, (320, 320), clip)
            self.assertTrue(rendered.is_file())
            self.assertTrue(still.is_file())
            self.assertGreater(core.probe(clip)['duration'], 1.0)

            first = Path(folder) / 'first.png'
            last = Path(folder) / 'last.png'
            core.run([core.FFMPEG, '-y', '-v', 'error', '-i', str(clip),
                      '-frames:v', '1', str(first)])
            core.run([core.FFMPEG, '-y', '-v', 'error', '-sseof', '-0.2', '-i', str(clip),
                      '-frames:v', '1', str(last)])
            self.assertGreater(
                diff_ratio(Image.open(first), Image.open(last)), 0.01,
                'intel_board 输出必须真的在动，不能是静态图加滤镜',
            )

    def test_style_reaches_shots_through_the_router(self):
        from visual_director.router import apply_routes
        project = {
            'options': {'aspect_ratio': '9:16', 'motion_style': 'intel_board'},
            'visual_master_plan': {'segments': [{
                'id': 'S001', 'visual_role': 'M', 'motion_type': 'M_NUMBER',
                'text': '首月单座席成本 14 美元', 'duration': 9,
            }]},
            'shots': [{'id': 'm1', 'visual_segment_id': 'S001'}],
        }
        apply_routes(project)
        shot = project['shots'][0]
        self.assertEqual(shot['motion_style'], 'intel_board')
        self.assertEqual(shot['motion_plan']['style'], 'intel_board')
        self.assertEqual(shot['motion_plan']['props']['aspect_ratio'], '9:16')

    def test_router_defaults_to_legacy_style_when_unset(self):
        from visual_director.router import apply_routes
        project = {
            'options': {'aspect_ratio': '16:9'},
            'visual_master_plan': {'segments': [{
                'id': 'S001', 'visual_role': 'M', 'motion_type': 'M_TITLE',
                'text': '标题', 'duration': 4,
            }]},
            'shots': [{'id': 'm1', 'visual_segment_id': 'S001'}],
        }
        apply_routes(project)
        self.assertEqual(project['shots'][0]['motion_style'], 'scene_flow')


if __name__ == '__main__':
    unittest.main()
