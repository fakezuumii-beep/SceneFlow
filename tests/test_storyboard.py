import copy
import unittest

import storyboard


def semantic(candidate, semantic_type, subject=''):
    return {'id':candidate['id'],'text':candidate['text'],'semantic_type':semantic_type,
            'visual_subject':subject,'importance':'normal','emotion':'neutral'}


class StoryboardRuleTests(unittest.TestCase):
    def setUp(self):
        self.rules=storyboard.load_rules()

    def test_llm_contract_rejects_editing_fields(self):
        candidates=[{'id':0,'text':'一句话。'}]
        good={'segments':[semantic(candidates[0],'opinion')]}
        self.assertEqual(storyboard.validate_semantic_response(good,candidates,self.rules)[0]['semantic_type'],'opinion')
        for field in ('start','end','duration','kind','shots','shot_count','from','to'):
            bad=copy.deepcopy(good);bad['segments'][0][field]=1
            with self.assertRaises(ValueError):storyboard.validate_semantic_response(bad,candidates,self.rules)

    def test_scores_are_loaded_from_configuration(self):
        event=semantic({'id':0,'text':'他来到北京。'},'event','年轻人初到北京')
        opinion=semantic({'id':1,'text':'我认为这很重要。'},'opinion','')
        self.assertEqual(storyboard.score_candidate(event,self.rules)[0],4)
        self.assertEqual(storyboard.score_candidate(opinion,self.rules)[0],-2)
        self.assertEqual(set(storyboard.score_candidate(event,self.rules)[1][0]),{'rule','value'})

    def test_zero_to_two_uses_whole_episode_ratio_only(self):
        candidates=[{'id':i,'start':i*2,'end':i*2+1.8,'text':f'段落{i}。'} for i in range(4)]
        semantics=[semantic(candidates[0],'hook'),semantic(candidates[1],'intro','温州苍南'),
                   semantic(candidates[2],'event','粉紫色日落'),semantic(candidates[3],'summary')]
        result=storyboard.classify_candidates(candidates,semantics,8,60,self.rules)
        self.assertEqual([item['broll_score'] for item in result],[-2,0,4,-2])
        self.assertEqual([item['kind'] for item in result],['A','B','B','A'])
        self.assertIn('全片 B-roll',result[1]['decision_reason'])
        lower=storyboard.classify_candidates(candidates,semantics,8,25,self.rules)
        self.assertEqual([item['kind'] for item in lower],['A','A','B','A'])

    def test_short_merge_uses_duration_weighted_score_and_auditable_breakdown(self):
        rules=copy.deepcopy(self.rules);rules['anchors']={'opening_aroll':False,'closing_aroll':False}
        items=[
            {'candidate_ids':[0],'text':'短句，','start':0,'end':1,'duration':1,'semantic_type':'opinion',
             'visual_subject':'','broll_score':-2,'score_breakdown':[{'rule':'semantic_type','value':-2}],
             'kind':'A','decision_reason':'测试'},
            {'candidate_ids':[1],'text':'明确事件。','start':1,'end':4,'duration':3,'semantic_type':'event',
             'visual_subject':'日落','broll_score':4,'score_breakdown':[{'rule':'semantic_type','value':2},{'rule':'visual_subject','value':2}],
             'kind':'B','decision_reason':'测试'},
        ]
        merged=storyboard.merge_short_narratives(items,rules,4,60)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['broll_score'],2.5)
        self.assertEqual(round(sum(part['value'] for part in merged[0]['score_breakdown']),3),2.5)
        self.assertEqual([(part['duration'],part['score']) for part in merged[0]['score_weighting']],[(1.0,-2.0),(3.0,4.0)])
        self.assertEqual(merged[0]['kind'],'B')
        self.assertIn('实际时长加权',merged[0]['decision_reason'])

    def test_d1_disputed_shots_are_locked_to_content_and_global_ratio_rules(self):
        a02=storyboard.score_candidate(semantic({'id':2,'text':'温州苍南'},'intro','温州苍南'),self.rules)[0]
        a12=storyboard.score_candidate(semantic({'id':18,'text':'下棋晒网的原住民'},'person','原住民'),self.rules)[0]
        a18,_=storyboard._weighted_score_details([
            {'candidate_ids':[28],'duration':2.86,'score':4,'score_breakdown':[{'rule':'semantic_type','value':2},{'rule':'visual_subject','value':2}]},
            {'candidate_ids':[29],'duration':1.68,'score':-2,'score_breakdown':[{'rule':'semantic_type','value':-2}]},
        ])
        a20,_=storyboard._weighted_score_details([
            {'candidate_ids':[31],'duration':1.68,'score':-2,'score_breakdown':[{'rule':'semantic_type','value':-2}]},
            {'candidate_ids':[32],'duration':2.58,'score':0,'score_breakdown':[{'rule':'semantic_type','value':-2},{'rule':'visual_subject','value':2}]},
        ])
        self.assertEqual((a02,a12,a18,a20),(0,4,1.78,-0.789))
        rules=copy.deepcopy(self.rules);rules['anchors']={'opening_aroll':False,'closing_aroll':False}
        def item(name,seconds,score):
            return {'name':name,'duration':seconds,'broll_score':score,'decision_reason':''}
        projected=storyboard._assign_kinds_by_ratio([
            item('开场明确A',47.24,-2),item('A-02',5.22,a02),item('其他明确B',36,4),
            item('A-12',3.02,a12),item('A-18',4.54,a18),item('A-20',4.26,a20),
        ],100.28,60,rules)
        kinds={entry['name']:entry['kind'] for entry in projected}
        self.assertEqual(kinds['A-02'],'B')
        self.assertEqual(kinds['A-12'],'B')
        self.assertEqual(kinds['A-18'],'B')
        self.assertEqual(kinds['A-20'],'A')

    def test_short_candidate_merges_and_visual_layer_stays_separate(self):
        candidates=[
            {'id':0,'start':0,'end':1.0,'text':'但这个决定，'},
            {'id':1,'start':1.1,'end':5.0,'text':'后来彻底改变了他的人生。'},
            {'id':2,'start':5.2,'end':9.8,'text':'这是我的结论。'},
        ]
        semantics=[semantic(candidates[0],'transition'),semantic(candidates[1],'event','人生转折'),semantic(candidates[2],'summary')]
        narratives,shots=storyboard.build_timeline(candidates,semantics,10,60,self.rules)
        self.assertEqual(narratives[0]['candidate_ids'],[0,1])
        self.assertEqual(narratives[0]['text'],'但这个决定，后来彻底改变了他的人生。')
        self.assertTrue(all(s['end']-s['start']>=2 for s in shots))
        self.assertTrue(all(s['narrative_ids'] for s in shots))

    def test_only_b_to_a_waits_for_outgoing_word_release(self):
        items=[
            {'kind':'A','start':0,'end':5,'duration':5},
            {'kind':'B','start':5,'end':11,'duration':6},
            {'kind':'A','start':11,'end':15,'duration':4},
            {'kind':'B','start':15,'end':20,'duration':5},
        ]
        result=storyboard.refine_directional_boundaries(
            items,[{'start':11.16,'end':12.06}],self.rules)
        self.assertEqual(result[0]['end'],5)  # A->B remains the semantic cut.
        self.assertEqual(result[1]['end'],11.227)
        self.assertEqual(result[2]['start'],11.227)
        self.assertEqual(result[2]['end'],15)
        self.assertEqual(result[1]['timing_adjustment']['source'],'silence')
        self.assertEqual(result[1]['timing_adjustment']['shift'],.227)

    def test_b_to_a_uses_short_guard_when_no_stable_silence_is_found(self):
        items=[
            {'kind':'B','start':0,'end':4,'duration':4},
            {'kind':'A','start':4,'end':8,'duration':4},
        ]
        result=storyboard.refine_directional_boundaries(items,[],self.rules)
        self.assertEqual((result[0]['end'],result[1]['start']),(4.067,4.067))
        self.assertEqual(result[0]['timing_adjustment']['source'],'fallback')

    def test_directional_shift_does_not_claim_text_from_the_next_narrative(self):
        candidates=[
            {'id':0,'start':0,'end':1.8,'text':'人物开场。'},
            {'id':1,'start':2,'end':5.8,'text':'温州苍南。'},
            {'id':2,'start':6,'end':9.8,'text':'人物观点。'},
        ]
        semantics=[semantic(candidates[0],'hook'),semantic(candidates[1],'location','温州苍南'),
                   semantic(candidates[2],'summary')]
        _,shots=storyboard.build_timeline(
            candidates,semantics,10,60,self.rules,[{'start':6.16,'end':6.9}])
        b=next(shot for shot in shots if shot['kind']=='B')
        a=next(shot for shot in shots if shot['kind']=='A' and shot['start']>2)
        self.assertEqual((b['end'],a['start']),(6.227,6.227))
        self.assertEqual((b['from'],b['to'],b['text']),(1,1,'温州苍南。'))
        self.assertEqual((a['from'],a['to'],a['text']),(2,2,'人物观点。'))

    def test_long_aroll_uses_semantic_nodes_and_non_fixed_changes(self):
        candidates=[{'id':i,'start':i*4,'end':i*4+3.8,'text':f'观点{i}。'} for i in range(4)]
        semantics=[semantic(c,'opinion') for c in candidates]
        narratives,shots=storyboard.build_timeline(candidates,semantics,16,60,self.rules)
        self.assertTrue(all(n['kind']=='A' for n in narratives))
        self.assertTrue(all(s['kind']=='A' for s in shots))
        self.assertGreaterEqual(len(shots),3)
        self.assertEqual([s['start'] for s in shots],[0,4,12])
        self.assertEqual(shots[0]['visual_change'],'hold')
        self.assertTrue(all(s['visual_change'] in ('cut_in','cut_out','push_in','pull_out') for s in shots[1:]))
        self.assertTrue(all(s['cut_reason']=='完整句结束' for s in shots[1:]))
        self.assertTrue(all(isinstance(n['id'],str) and n['id'].startswith('n-') for n in narratives))
        self.assertEqual(''.join(s['text'] for s in shots),''.join(c['text'] for c in candidates))

    def test_eleven_second_aroll_chooses_transition_not_midpoint(self):
        candidates=[
            {'id':0,'start':0,'end':3.7,'text':'前半段只是铺垫，'},
            {'id':1,'start':4.2,'end':10.7,'text':'但是这里开始新的观点。'},
        ]
        semantics=[semantic(c,'opinion') for c in candidates]
        _,shots=storyboard.build_timeline(candidates,semantics,11,60,self.rules)
        self.assertEqual([s['start'] for s in shots],[0,4.2])
        self.assertIn('转折或承接词',shots[1]['cut_reason'])
        self.assertNotEqual(shots[1]['start'],5.5)

    def test_eleven_second_aroll_without_semantic_node_stays_one_shot(self):
        candidates=[
            {'id':0,'start':0,'end':5,'text':'这是一段没有自然节点的连续表达'},
            {'id':1,'start':5.1,'end':10.8,'text':'仍然延续同一个表达'},
        ]
        semantics=[semantic(c,'opinion') for c in candidates]
        _,shots=storyboard.build_timeline(candidates,semantics,11,60,self.rules)
        self.assertEqual(len(shots),1)
        self.assertEqual(shots[0]['visual_change'],'hold')
        self.assertEqual(shots[0]['camera'],'medium')

    def test_cut_score_prefers_pause_and_new_viewpoint_over_comma(self):
        candidates=[
            {'id':0,'start':0,'end':3.8,'text':'这只是普通的逗号，'},
            {'id':1,'start':4.0,'end':7.5,'text':'这里还在继续，'},
            {'id':2,'start':8.2,'end':11.5,'text':'真正的问题是方向变了。'},
        ]
        semantics=[semantic(c,'opinion') for c in candidates]
        nodes=storyboard.semantic_cut_nodes(candidates,semantics,0,12,self.rules)
        self.assertGreater(nodes[1]['score'],nodes[0]['score'])
        self.assertIn('明显停顿',nodes[1]['reasons'])
        self.assertIn('新观点开始',nodes[1]['reasons'])

    def test_duration_tiers_match_editorial_ranges(self):
        self.assertEqual(storyboard._change_limits(8,self.rules),(0,0))
        self.assertEqual(storyboard._change_limits(12,self.rules),(0,1))
        self.assertEqual(storyboard._change_limits(18,self.rules),(1,2))
        self.assertEqual(storyboard._change_limits(22,self.rules),(2,3))

    def test_over_eighteen_without_natural_nodes_is_flagged_not_hard_cut(self):
        candidates=[{'id':0,'start':0,'end':21.8,'text':'这是一个没有任何可用语义边界的连续长句'}]
        semantics=[semantic(candidates[0],'opinion')]
        _,shots=storyboard.build_timeline(candidates,semantics,22,60,self.rules)
        self.assertEqual(len(shots),1)
        self.assertIn('复查语义边界',shots[0]['editorial_review'])

    def test_long_broll_uses_natural_boundaries_and_multiple_visuals(self):
        candidates=[{'id':i,'start':i*3.2,'end':i*3.2+3,'text':f'动作{i}，'} for i in range(4)]
        semantics=[semantic(c,'action','年轻人乘火车去香港') for c in candidates]
        narratives,shots=storyboard.build_timeline(candidates,semantics,12.8,60,self.rules)
        b=[s for s in shots if s['kind']=='B']
        self.assertGreaterEqual(len(b),2)
        self.assertTrue(all(s['end']-s['start']<=6 for s in b))
        observed={round(c['start'],3) for c in candidates[1:]}
        self.assertTrue(all(s['end'] in observed or s['end']==12.8 for s in b))
        self.assertTrue(all(s['visual_subject']=='年轻人乘火车去香港' for s in b))


if __name__=='__main__':unittest.main()
