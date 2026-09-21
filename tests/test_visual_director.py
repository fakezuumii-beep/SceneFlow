import unittest

import storyboard
from motion.template_router import MOTION_TYPES, build_motion_plan
from visual_director import rhythm_validator
from visual_director.master_plan import from_shots, motion_queue_markdown, normalize_project, set_segment_role, to_markdown
from visual_director.router import apply_routes
from visual_director.schema import validate_director_response
from visual_director.timeline import build_visual_timeline


def director_segment(segment_id, ids, text, semantic_type, role, **extra):
    value = {
        'segment_id':segment_id,'candidate_ids':ids,'text':text,
        'semantic_type':semantic_type,'visual_role':role,'confidence':.95,
        'entities':[],'visual_subject':'','evidence_required':False,
        'evidence_target':None,'evidence_type':None,'search_query':None,
        'stock_search_query':None,'stock_search_query_alt':[],
        'fallback':'A','recording_required':False,'recording_instruction':None,
        'motion_type':None,'motion_data':None,'generation_concept':None,'importance':3,
        'continuity_group':'CG01','reason':'测试判断',
    }
    value.update(extra)
    return value


class VisualDirectorTests(unittest.TestCase):
    def setUp(self):
        self.rules=storyboard.load_rules()

    def test_schema_separates_generic_b_from_real_evidence(self):
        candidates=[
            {'id':0,'text':'OpenAI发布新模型。'},
            {'id':1,'text':'越来越多企业开始使用AI办公。'},
        ]
        response={'video_type':'ai_news','overview':'测试','segments':[
            director_segment(
                'S001',[0],candidates[0]['text'],'event','E',
                evidence_required=True,evidence_target='OpenAI官方公告',
                search_query='OpenAI official announcement',fallback='A',
            ),
            director_segment(
                'S002',[1],candidates[1]['text'],'abstract','B',
                visual_subject='办公室中的AI工作场景',
                stock_search_query='AI office working computer',
                stock_search_query_alt=['office technology','people working computer'],
            ),
        ]}
        normalized=validate_director_response(response,candidates,self.rules)
        self.assertEqual([item['visual_role'] for item in normalized['segments']],['E','B'])
        self.assertEqual(normalized['segments'][0]['evidence_target'],'OpenAI官方公告')
        self.assertEqual(normalized['segments'][1]['stock_search_query_alt'][0],'office technology')

        invalid={'video_type':'ai_news','overview':'测试','segments':[
            director_segment('S001',[0],candidates[0]['text'],'event','E',evidence_required=False),
            director_segment('S002',[1],candidates[1]['text'],'abstract','B',stock_search_query='AI office'),
        ]}
        with self.assertRaisesRegex(ValueError,'E 类必须是真实证据'):
            validate_director_response(invalid,candidates,self.rules)

    def test_legacy_b_maps_to_b_without_reclassifying_assets(self):
        project={
            'id':'legacy','duration':4,'video_profile':'general',
            'shots':[{'id':'b1','kind':'B','start':0,'end':4,'text':'打开官网查看办公室工作',
                      'title':'办公室','asset':'assets/office.mp4',
                      'source':{'provider':'pexels','id':'office'}}],
        }
        self.assertTrue(normalize_project(project))
        shot=project['shots'][0]
        self.assertEqual(shot['visual_role'],'B')
        self.assertEqual(shot['asset'],'assets/office.mp4')
        self.assertTrue(shot['generic_stock_allowed'])
        plan=project['visual_master_plan']
        routes=apply_routes(project)
        self.assertEqual(plan['segments'][0]['visual_role'],'B')
        self.assertEqual(routes['S001']['processor'],'stock')
        self.assertTrue(routes['S001']['generic_stock_allowed'])

    def test_evidence_route_never_uses_generic_stock(self):
        plan=from_shots({
            'duration':5,'shots':[{'id':'e1','kind':'B','start':0,'end':5,'text':'OpenAI发布新模型',
                                   'visual_role':'E','evidence_required':True,
                                   'evidence_target':'OpenAI官方公告',
                                   'search_query':'OpenAI official announcement'}],
        })
        project={'options':{'aspect_ratio':'9:16'},'shots':[{'id':'e1','visual_segment_id':'S001',
                 'visual_role':'E','kind':'B'}],'visual_master_plan':plan}
        route=apply_routes(project)['S001']
        self.assertEqual(route['processor'],'evidence')
        self.assertFalse(route['generic_stock_allowed'])
        self.assertEqual(project['shots'][0]['kind'],'B')

    def test_manual_role_change_clears_incompatible_resolver_fields(self):
        project={
            'duration':5,
            'shots':[{'id':'e1','kind':'B','start':0,'end':5,'text':'OpenAI发布新模型',
                      'visual_role':'E','visual_segment_id':'S001',
                      'evidence_required':True,'evidence_target':'OpenAI官方公告',
                      'search_query':'OpenAI official announcement'}],
        }
        project['visual_master_plan']=from_shots(project)
        self.assertTrue(set_segment_role(project,'S001','B'))
        segment=project['visual_master_plan']['segments'][0]
        self.assertEqual(segment['visual_role'],'B')
        self.assertFalse(segment['evidence_required'])
        self.assertIsNone(segment['evidence_target'])
        self.assertIsNone(segment['search_query'])
        self.assertFalse(segment['stock_search_query'])

    def test_r_role_uses_evidence_execution_with_aroll_fallback(self):
        plan=from_shots({
            'duration':5,'shots':[{'id':'r1','kind':'B','start':0,'end':5,
                                   'visual_role':'R','visual_segment_id':'S001',
                                   'recording_required':True,
                                   'recording_instruction':'打开官网查看入口',
                                   'evidence_target':'OpenAI官网入口'}],
        })
        project={'options':{'aspect_ratio':'9:16'},'shots':[{'id':'r1','visual_segment_id':'S001',
                 'visual_role':'R','kind':'B'}],'visual_master_plan':plan}
        route=apply_routes(project)['S001']
        self.assertEqual(route['processor'],'evidence')
        self.assertEqual(route['execution_as'],'E')
        self.assertEqual(route['fallback_role'],'E')

    def test_unified_timeline_covers_all_active_visual_roles(self):
        shots=[]
        for index,role in enumerate(('A','B','E','M','G')):
            shot={'id':f'{role}{index}','kind':'A' if role=='A' else 'B',
                  'visual_role':role,'start':index,'end':index+1,
                  'visual_segment_id':f'S{index+1:03d}'}
            if role=='A':shot['aroll_asset']='assets/a.mp4'
            else:shot['asset']=f'assets/{role.lower()}.mp4'
            shots.append(shot)
        timeline=build_visual_timeline({'id':'p','duration':5,'shots':shots})
        self.assertEqual([clip['visual_role'] for clip in timeline['clips']],['A','B','E','M','G'])
        self.assertEqual([clip['start'] for clip in timeline['clips']],[0,1,2,3,4])
        self.assertTrue(all(clip['asset']['type']=='video' for clip in timeline['clips']))

    def test_rhythm_measures_runs_by_span_and_never_exceeds_the_episode(self):
        # A short phrase merged into a continuous A-roll run stays in the plan
        # as a child of its parent, so summing the raw list reported more
        # visual seconds than the episode is long.
        plan={'segments':[
            {'id':'s1','start':0,'end':5,'visual_role':'A','visual_subject':'开场'},
            {'id':'s2','start':5,'end':20,'visual_role':'A','visual_subject':'观点'},
            {'id':'s3','start':10,'end':14,'visual_role':'A','visual_subject':'合并子段'},
            {'id':'s4','start':20,'end':26,'visual_role':'E','visual_subject':'证据'},
        ]}
        shots=[{'id':'x1','start':0,'end':5,'visual_role':'A'},
               {'id':'x2','start':5,'end':20,'visual_role':'A'},
               {'id':'x3','start':20,'end':26,'visual_role':'E'}]
        result=rhythm_validator.validate(plan,shots)
        self.assertEqual(result['role_counts'],{'A':2,'B':0,'E':1,'R':0,'M':0,'G':0})
        self.assertEqual(result['role_duration']['A'],20.0)
        self.assertEqual(sum(result['role_duration'].values()),26.0)
        messages=[warning['message'] for warning in result['warnings']]
        self.assertIn('连续 A 类视觉 20.0 秒，建议检查其中是否包含证据或动效单元',messages)
        self.assertNotIn('连续 A 类视觉 24.0 秒，建议检查其中是否包含证据或动效单元',messages)

    def test_rhythm_without_shots_still_uses_run_spans(self):
        plan={'segments':[
            {'id':'s1','start':0,'end':5,'visual_role':'A','visual_subject':'开场'},
            {'id':'s2','start':5,'end':20,'visual_role':'A','visual_subject':'观点'},
            {'id':'s3','start':10,'end':14,'visual_role':'A','visual_subject':'合并子段'},
        ]}
        result=rhythm_validator.validate(plan)
        self.assertEqual(result['role_duration']['A'],20.0)
        self.assertEqual(result['role_counts']['A'],2)

    def test_skill_style_master_plan_and_motion_queue_markdown(self):
        plan=from_shots({
            'duration':6,
            'shots':[
                {'id':'a1','kind':'A','visual_role':'A','visual_segment_id':'S001',
                 'start':0,'end':2,'text':'主播观点'},
                {'id':'m1','kind':'B','visual_role':'M','visual_segment_id':'S002',
                 'start':2,'end':6,'text':'价格从15美元降到10美元','motion_type':'M_COMPARE'},
            ],
        })
        plan['segments'][1]['execution']={'material_strategy':'motion_template'}
        master=to_markdown(plan)
        queue=motion_queue_markdown(plan)
        self.assertIn('Visual Master Plan',master)
        self.assertIn('| S002 |',master)
        self.assertIn('Motion Production Queue',queue)
        self.assertIn('FX01',queue)
        self.assertIn('M_COMPARE',queue)

    def test_all_eight_motion_templates_accept_all_aspect_ratios(self):
        for motion_type in MOTION_TYPES:
            for aspect in ('9:16','1:1','16:9'):
                result=build_motion_plan({
                    'motion_type':motion_type,'text':'OpenAI、Google 和 Anthropic',
                    'visual_subject':'三家AI公司','entities':[],
                },6,aspect)
                self.assertEqual(result['template'],motion_type)
                self.assertEqual(result['props']['aspect_ratio'],aspect)
                self.assertEqual(result['props']['duration'],6)

    def test_ai_news_acceptance_keeps_named_entities_as_evidence(self):
        texts=[
            '今天AI圈最值得关注的是OpenAI的新动作。',
            'OpenAI今天正式发布了GPT-X。',
            '新模型推理能力提升了35%。',
            'API价格从15美元下降到10美元。',
            '真正重要的是AI服务价格战正在加速。',
            'OpenAI、Google和Anthropic正在走不同路线。',
            '打开OpenAI官网可以看到新的API入口。',
            '未来一年AI应用开发成本可能继续下降。',
        ]
        candidates=[{'id':index,'text':text} for index,text in enumerate(texts)]
        segments=[
            director_segment('S001',[0],texts[0],'hook','A'),
            director_segment('S002',[1],texts[1],'event','E',evidence_required=True,
                             evidence_target='GPT-X 官方发布页面',
                             search_query='OpenAI GPT-X official announcement'),
            director_segment('S003',[2],texts[2],'data','M',motion_type='M_NUMBER',
                             motion_data={'number':'35%','label':'推理性能提升'}),
            director_segment('S004',[3],texts[3],'data','M',motion_type='M_COMPARE',
                             motion_data={'before':'$15','after':'$10','label':'API价格'}),
            director_segment('S005',[4],texts[4],'opinion','A'),
            director_segment('S006',[5],texts[5],'abstract','B',
                             visual_subject='AI公司路线对比',
                             stock_search_query='AI company technology comparison'),
            director_segment('S007',[6],texts[6],'process','R',recording_required=True,
                             recording_instruction='打开 OpenAI 官网并展示 API 入口'),
            director_segment('S008',[7],texts[7],'abstract','A'),
        ]
        result=validate_director_response(
            {'video_type':'ai_news','overview':'验收稿','segments':segments},
            candidates,self.rules,
        )
        roles=[item['visual_role'] for item in result['segments']]
        self.assertEqual(roles,['A','E','M','M','A','B','R','A'])
        self.assertNotIn('B',roles[:2])
        self.assertEqual(result['segments'][1]['evidence_target'],'GPT-X 官方发布页面')


if __name__=='__main__':
    unittest.main()
