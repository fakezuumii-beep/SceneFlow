import copy
import unittest

import storyboard


def semantic(candidate, semantic_type, subject='', importance='normal', emotion='neutral'):
    return {'id':candidate['id'],'text':candidate['text'],'semantic_type':semantic_type,
            'visual_subject':subject,'importance':importance,'emotion':emotion}


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

    def test_dual_values_use_visual_subject_importance_and_emotion(self):
        event=semantic({'id':0,'text':'他来到北京。'},'event','年轻人初到北京')
        opinion=semantic({'id':1,'text':'我认为这很重要。'},'opinion','')
        emotional=semantic({'id':2,'text':'这是最重要的一刻。'},'event','颁奖礼','high','surprised')
        self.assertEqual(storyboard.value_candidate(event,self.rules)[:2],(4,1))
        self.assertEqual(storyboard.value_candidate(opinion,self.rules)[:2],(0,3))
        self.assertEqual(storyboard.value_candidate(emotional,self.rules)[:2],(4,4.5))
        self.assertEqual(set(storyboard.value_candidate(event,self.rules)[2][0]),{'rule','value'})

    def test_weak_semantic_passage_follows_matching_strong_context(self):
        candidates=[{'id':i,'start':i*2,'end':i*2+1.8,'text':f'段落{i}。'} for i in range(4)]
        semantics=[semantic(candidates[0],'hook'),semantic(candidates[1],'quote',''),
                   semantic(candidates[2],'other','粉紫色日落'),semantic(candidates[3],'summary')]
        result=storyboard.classify_candidates(candidates,semantics,8,25,self.rules)
        self.assertEqual([(item['visual_value'],item['host_value']) for item in result],[(0,3),(0,2),(2,1),(0,3)])
        self.assertEqual([item['kind'] for item in result],['A','A','A','A'])
        self.assertIn('前后强语义均为 A-roll',result[2]['decision_reason'])

    def test_broll_ratio_is_legacy_and_does_not_change_semantic_result(self):
        candidates=[{'id':i,'start':i*3,'end':i*3+2.8,'text':f'段落{i}。'} for i in range(3)]
        semantics=[semantic(candidates[0],'hook'),semantic(candidates[1],'event','街道人群'),semantic(candidates[2],'summary')]
        low=storyboard.classify_candidates(candidates,semantics,9,0,self.rules)
        high=storyboard.classify_candidates(candidates,semantics,9,80,self.rules)
        self.assertEqual([item['kind'] for item in low],['A','B','A'])
        self.assertEqual([item['kind'] for item in low],[item['kind'] for item in high])

    def test_unenclosed_weak_passage_uses_duration_weighted_semantic_lean(self):
        items=[{'name':name,'text':name,'candidate_ids':[name],'duration':2,
                'visual_value':visual,'host_value':1,'decision_reason':''}
               for name,visual in [('weak',.5),('best',1.9),('middle',1.4),('second',1.7)]]
        first=storyboard._assign_kinds_by_semantic_flow(items,self.rules)
        second=storyboard._assign_kinds_by_semantic_flow(list(reversed(items)),self.rules)
        self.assertTrue(all(item['kind']=='B' for item in first))
        self.assertEqual({item['name']:item['kind'] for item in first},
                         {item['name']:item['kind'] for item in second})

    def test_short_merge_uses_duration_weighted_score_and_auditable_breakdown(self):
        rules=copy.deepcopy(self.rules)
        items=[
            {'candidate_ids':[0],'text':'短句，','start':0,'end':1,'duration':1,'semantic_type':'opinion',
             'visual_subject':'','visual_value':0,'host_value':3,
             'visual_value_breakdown':[{'rule':'semantic_type','value':0}],
             'host_value_breakdown':[{'rule':'semantic_type','value':2},{'rule':'importance','value':1},{'rule':'emotion','value':0}],
             'kind':'A','decision_reason':'测试'},
            {'candidate_ids':[1],'text':'明确事件。','start':1,'end':4,'duration':3,'semantic_type':'event',
             'visual_subject':'日落','visual_value':4,'host_value':1,
             'visual_value_breakdown':[{'rule':'semantic_type','value':2},{'rule':'visual_subject','value':2}],
             'host_value_breakdown':[{'rule':'semantic_type','value':0},{'rule':'importance','value':1},{'rule':'emotion','value':0}],
             'kind':'B','decision_reason':'测试'},
        ]
        merged=storyboard.merge_short_narratives(items,rules,4,60)
        self.assertEqual(len(merged),1)
        self.assertEqual((merged[0]['visual_value'],merged[0]['host_value']),(3,1.5))
        self.assertEqual(round(sum(part['value'] for part in merged[0]['visual_value_breakdown']),3),3)
        self.assertEqual([(part['duration'],part['visual_value'],part['host_value']) for part in merged[0]['value_weighting']],
                         [(1.0,0.0,3.0),(3.0,4.0,1.0)])
        self.assertEqual(merged[0]['kind'],'B')
        self.assertIn('实际时长加权',merged[0]['decision_reason'])

    def test_visual_subject_boilerplate_is_normalized_to_empty(self):
        candidate={'id':0,'text':'这是抽象表达。'}
        for value in ('没有具体可视化对象','无明确主体','不适用','抽象观点','No concrete visual subject'):
            payload={'segments':[semantic(candidate,'other',value)]}
            item=storyboard.validate_semantic_response(payload,[candidate],self.rules)[0]
            self.assertEqual(item['visual_subject'],'')
            self.assertEqual(storyboard.value_candidate(item,self.rules)[0],0)

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

    def test_merged_broll_searches_best_visual_child_not_longest_child(self):
        rules=copy.deepcopy(self.rules)
        candidates=[
            {'id':0,'start':0,'end':.9,'text':'火山突然喷发，'},
            {'id':1,'start':1,'end':3.9,'text':'这件事让我们继续思考。'},
        ]
        semantics=[semantic(candidates[0],'event','夜间火山喷发'),semantic(candidates[1],'other','','low')]
        narratives,shots=storyboard.build_timeline(candidates,semantics,4,100,rules)
        self.assertEqual(len(narratives),1)
        self.assertEqual(narratives[0]['kind'],'B')
        self.assertEqual(narratives[0]['semantic_type'],'other')  # longest child remains the narrative dominant
        self.assertEqual(narratives[0]['visual_source']['candidate_ids'],[0])
        self.assertEqual(shots[0]['visual_subject'],'夜间火山喷发')
        self.assertEqual(shots[0]['keywords'][0],'夜间火山喷发')

    def test_long_broll_is_not_broken_by_forced_host_return(self):
        rules=copy.deepcopy(self.rules)
        candidates=[{'id':i,'start':i*3,'end':i*3+2.8,'text':f'段落{i}。'} for i in range(5)]
        semantics=[semantic(candidates[0],'hook'),semantic(candidates[1],'event','城市街道'),
                   semantic(candidates[2],'action','获奖者激动发言','high','surprised'),
                   semantic(candidates[3],'event','人群庆祝'),semantic(candidates[4],'summary')]
        narratives,_=storyboard.build_timeline(candidates,semantics,15,100,rules)
        self.assertEqual([item['kind'] for item in narratives],['A','B','B','B','A'])
        self.assertIn('前后强语义均为 B-roll',narratives[2]['decision_reason'])

        no_node=[semantic(candidates[0],'hook')]+[
            semantic(candidates[i],'event','城市街道') for i in range(1,4)]+[semantic(candidates[4],'summary')]
        narratives,_=storyboard.build_timeline(candidates,no_node,15,100,rules)
        self.assertEqual([item['kind'] for item in narratives],['A','B','B','B','A'])

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

    def test_long_aroll_is_one_continuous_shot(self):
        candidates=[{'id':i,'start':i*4,'end':i*4+3.8,'text':f'观点{i}。'} for i in range(4)]
        semantics=[semantic(c,'opinion') for c in candidates]
        narratives,shots=storyboard.build_timeline(candidates,semantics,16,60,self.rules)
        self.assertTrue(all(n['kind']=='A' for n in narratives))
        self.assertEqual(len(shots),1)
        self.assertEqual((shots[0]['start'],shots[0]['end']),(0,16))
        self.assertEqual(shots[0]['visual_change'],'hold')
        self.assertEqual(shots[0]['aroll_edit_mode'],'semantic_continuous')
        self.assertIsNone(shots[0]['motion'])
        self.assertTrue(all(isinstance(n['id'],str) and n['id'].startswith('n-') for n in narratives))
        self.assertEqual(''.join(s['text'] for s in shots),''.join(c['text'] for c in candidates))

    def test_eleven_second_aroll_does_not_split_again_at_transition(self):
        candidates=[
            {'id':0,'start':0,'end':3.7,'text':'前半段只是铺垫，'},
            {'id':1,'start':4.2,'end':10.7,'text':'但是这里开始新的观点。'},
        ]
        semantics=[semantic(c,'opinion') for c in candidates]
        _,shots=storyboard.build_timeline(candidates,semantics,11,60,self.rules)
        self.assertEqual(len(shots),1)
        self.assertEqual((shots[0]['start'],shots[0]['end']),(0,11))
        self.assertEqual(shots[0]['cut_reason'],'')

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

    def test_h3_keeps_continuous_aroll_native_within_fifteen_seconds(self):
        candidates=[
            {'id':0,'start':0,'end':3.8,'text':'第一句。'},
            {'id':1,'start':4,'end':7.8,'text':'第二句。'},
            {'id':2,'start':8,'end':11.8,'text':'第三句。'},
        ]
        semantics=[semantic(c,'opinion') for c in candidates]
        _,shots=storyboard.build_timeline(candidates,semantics,12,60,self.rules,
                                          aroll_provider='autodl_h3')
        self.assertEqual(len(shots),1)
        self.assertEqual((shots[0]['start'],shots[0]['end']),(0,12))
        self.assertEqual(shots[0]['visual_change'],'h3_native')
        self.assertEqual(shots[0]['aroll_edit_mode'],'provider_native')
        self.assertIsNone(shots[0]['camera'])
        self.assertIsNone(shots[0]['motion'])

    def test_h3_long_aroll_stays_one_timeline_shot_for_provider_chunking(self):
        candidates=[{'id':i,'start':i*5,'end':i*5+4.8,'text':f'观点{i}。'} for i in range(4)]
        semantics=[semantic(c,'opinion') for c in candidates]
        _,shots=storyboard.build_timeline(candidates,semantics,20,60,self.rules,
                                          aroll_provider='autodl_h3')
        self.assertEqual(len(shots),1)
        self.assertEqual((shots[0]['start'],shots[0]['end']),(0,20))
        self.assertIn('超过 15 秒',shots[0]['editorial_review'])

    def test_current_episode_shape_keeps_middle_broll_continuous(self):
        candidates=[{'id':i,'start':i*4,'end':i*4+3.8,'text':f'当前项目段落{i}。'} for i in range(6)]
        semantics=[semantic(candidates[0],'hook'),semantic(candidates[1],'event','城市现场'),
                   semantic(candidates[2],'action','人物行动','high'),semantic(candidates[3],'location','街道'),
                   semantic(candidates[4],'process','制作过程'),semantic(candidates[5],'summary')]
        narratives,shots=storyboard.build_timeline(candidates,semantics,24,60,self.rules)
        self.assertEqual([item['kind'] for item in narratives],['A','B','B','B','B','A'])
        kinds=[]
        for shot in shots:
            if not kinds or kinds[-1]!=shot['kind']:kinds.append(shot['kind'])
        self.assertEqual(kinds,['A','B','A'])
        self.assertFalse(any('回到主持人' in item['decision_reason'] for item in narratives))

    def test_over_eighteen_aroll_stays_continuous_without_extra_warning(self):
        candidates=[{'id':0,'start':0,'end':21.8,'text':'这是一个没有任何可用语义边界的连续长句'}]
        semantics=[semantic(candidates[0],'opinion')]
        _,shots=storyboard.build_timeline(candidates,semantics,22,60,self.rules)
        self.assertEqual(len(shots),1)
        self.assertIsNone(shots[0]['editorial_review'])

    def test_long_broll_uses_natural_boundaries_and_multiple_visuals(self):
        candidates=[{'id':i,'start':i*3.2,'end':i*3.2+3,'text':f'动作{i}，'} for i in range(4)]
        semantics=[semantic(c,'action','年轻人乘火车去香港') for c in candidates]
        narratives,shots=storyboard.build_timeline(candidates,semantics,12.8,60,self.rules)
        b=[s for s in shots if s['kind']=='B']
        self.assertGreaterEqual(len(b),2)
        self.assertTrue(all(s['end']-s['start']<=6.5 for s in b))
        observed={round(c['start'],3) for c in candidates[1:]}
        self.assertTrue(all(s['end'] in observed or s['end']==12.8 for s in b))
        self.assertTrue(all(s['visual_subject']=='年轻人乘火车去香港' for s in b))


if __name__=='__main__':unittest.main()
