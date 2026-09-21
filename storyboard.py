"""Deterministic semantic-to-visual storyboard rules.

The LLM classifies candidate text only. This module keeps A/B selection tied to
semantic meaning, merges very short phrases, and builds a continuous timeline.
"""
from __future__ import annotations

import copy
import json
import math
import re
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / 'storyboard_rules.json'
FORBIDDEN_LLM_FIELDS = {
    'start', 'end', 'duration', 'kind', 'a_roll', 'b_roll', 'aroll', 'broll',
    'shot_count', 'shots', 'visual_shots', 'from', 'to',
}


def load_rules(path=RULES_PATH):
    rules=json.loads(Path(path).read_text(encoding='utf-8'))
    required=('version','semantic_types','importance_values','emotion_values','values','selection',
              'durations','directional_cuts')
    if any(key not in rules for key in required):raise ValueError('分镜规则配置不完整')
    if len(set(rules['semantic_types']))!=len(rules['semantic_types']):raise ValueError('分镜语义类型配置重复')
    return rules


def validate_semantic_response(payload, candidates, rules):
    items=payload.get('segments') if isinstance(payload,dict) else None
    if not isinstance(items,list) or len(items)!=len(candidates):
        raise ValueError('模型必须为每个候选段返回一条语义判断')
    output=[]
    for expected,item in zip(candidates,items):
        allowed={'id','text','semantic_type','visual_subject','importance','emotion'}
        if not isinstance(item,dict) or set(item)-allowed or FORBIDDEN_LLM_FIELDS.intersection(item):
            raise ValueError('模型返回了时间、A/B 或镜头决策字段')
        try:item_id=int(item.get('id'))
        except (TypeError,ValueError):raise ValueError('模型语义段 id 无效')
        if item_id!=expected['id']:raise ValueError('模型语义段顺序或 id 与原文不一致')
        if str(item.get('text','')).strip()!=str(expected['text']).strip():
            raise ValueError('模型修改了候选段原文')
        semantic=str(item.get('semantic_type','')).strip().lower()
        importance=str(item.get('importance','normal')).strip().lower()
        emotion=str(item.get('emotion','neutral')).strip().lower()
        if semantic not in rules['semantic_types']:raise ValueError('模型返回了未配置的 semantic_type')
        if importance not in rules.get('importance_values',['low','normal','high']):raise ValueError('模型返回了无效 importance')
        if emotion not in rules.get('emotion_values',['neutral']):raise ValueError('模型返回了无效 emotion')
        visual_subject=str(item.get('visual_subject','')).strip()[:160]
        output.append({
            'id':item_id,
            'text':str(expected['text']).strip(),
            'semantic_type':semantic,
            'visual_subject':visual_subject if searchable_visual_subject(visual_subject) else '',
            'importance':importance,
            'emotion':emotion,
        })
    return output


def timeline_bounds(index, candidates, duration):
    start=0.0 if index==0 else float(candidates[index]['start'])
    end=float(duration) if index==len(candidates)-1 else float(candidates[index+1]['start'])
    return round(start,3),round(end,3)


def searchable_visual_subject(value):
    text=re.sub(r'\s+',' ',str(value or '')).strip()
    if len(re.sub(r'[^\w\u3400-\u9fff]','',text))<2:return False
    normalized=re.sub(r'[\s\W_]+','',text.lower())
    exact={'无','没有','不适用','无明确主体','没有明确主体','无具体主体','无可视化对象',
           '没有具体可视化对象','抽象','抽象观点','抽象概念','观点','情绪','总结','转折',
           '主持人','说话的人','none','na','notapplicable','abstract','abstractopinion',
           'noconcretevisualsubject','noclearvisualsubject'}
    if normalized in exact:return False
    blocked_phrases=('没有具体可视化对象','无具体可视化对象','没有明确可视化对象','无明确可视化对象',
                     '没有明确主体','无明确主体','没有具体主体','无具体主体','不适用','抽象观点',
                     '抽象概念','无法可视化','无可视化内容','没有可视化内容','noconcretevisual',
                     'noclearvisual','nospecificvisual','notapplicable','abstractopinion')
    if any(phrase in normalized for phrase in blocked_phrases):return False
    if re.match(r'^(没有|无)(具体|明确)?的?(可视化)?(对象|主体|画面|内容|元素)',normalized):return False
    return True


def value_candidate(item, rules):
    """Return independent content values for B-roll visuals and host presence."""
    values=rules['values']
    visual=float(values['visual_semantic_type'].get(item['semantic_type'],0))
    visual_parts=[{'rule':'semantic_type','value':visual}]
    if searchable_visual_subject(item.get('visual_subject')):
        value=float(values['searchable_visual_subject']);visual+=value
        visual_parts.append({'rule':'visual_subject','value':value})
    semantic_host=float(values['host_semantic_type'].get(item['semantic_type'],0))
    importance=float(values['importance_host'][item['importance']])
    emotion=float(values['emotion_host'][item['emotion']])
    host=semantic_host+importance+emotion
    host_parts=[{'rule':'semantic_type','value':semantic_host},
                {'rule':'importance','value':importance},{'rule':'emotion','value':emotion}]
    return (round(visual,3),round(host,3),visual_parts,host_parts)


def _assign_kinds_by_semantic_flow(items, rules):
    """Use strong semantic decisions and smooth only enclosed weak passages."""
    output=copy.deepcopy(items);selection=rules['selection']
    definite_b=float(selection['definite_b_advantage']);definite_a=float(selection['definite_a_advantage'])
    for item in output:
        visual=float(item['visual_value']);host=float(item['host_value']);advantage=round(visual-host,3)
        item['value_advantage']=advantage
        if advantage<=definite_a:
            item['kind']='A';item['decision_reason']=f'视觉价值 {visual:g} / 人物价值 {host:g}，人物语义明确，判为 A-roll'
        elif advantage>=definite_b:
            item['kind']='B';item['decision_reason']=f'视觉价值 {visual:g} / 人物价值 {host:g}，画面语义明确，判为 B-roll'
        else:
            item['kind']=None
    index=0
    while index<len(output):
        if output[index]['kind'] is not None:index+=1;continue
        end=index
        while end+1<len(output) and output[end+1]['kind'] is None:end+=1
        left=output[index-1]['kind'] if index else None
        right=output[end+1]['kind'] if end+1<len(output) else None
        weighted=sum((float(output[i]['visual_value'])-float(output[i]['host_value']))*
                     float(output[i]['duration']) for i in range(index,end+1))
        enclosed=left if left and left==right else None
        chosen=enclosed or ('B' if weighted>0 else 'A')
        basis=(f'前后强语义均为 {chosen}-roll，保持同一段表达' if enclosed else
               f'弱语义段整体更偏 {"画面" if chosen=="B" else "人物"}')
        for i in range(index,end+1):
            item=output[i];item['kind']=chosen
            item['decision_reason']=(f'视觉价值 {float(item["visual_value"]):g} / 人物价值 {float(item["host_value"]):g}；'
                                     f'{basis}，判为 {chosen}-roll')
        index=end+1
    return output


def classify_candidates(candidates, semantics, duration, target_ratio, rules, assign=True):
    result=[]
    for index,(candidate,semantic) in enumerate(zip(candidates,semantics)):
        start,end=timeline_bounds(index,candidates,duration);seconds=round(end-start,3)
        visual,host,visual_breakdown,host_breakdown=value_candidate(semantic,rules)
        item={**copy.deepcopy(semantic),'candidate_ids':[candidate['id']],
              'start':start,'end':end,'duration':seconds,
              'visual_value':visual,'host_value':host,
              'visual_value_breakdown':visual_breakdown,'host_value_breakdown':host_breakdown,
              'value_weighting':[{'candidate_ids':[candidate['id']],'duration':seconds,
                                  'visual_value':visual,'host_value':host,
                                  'visual_value_breakdown':copy.deepcopy(visual_breakdown),
                                  'host_value_breakdown':copy.deepcopy(host_breakdown)}]}
        result.append(item)
    return _assign_kinds_by_semantic_flow(result,rules) if assign else result


def _merge_cost(short, neighbor, combined_seconds, rules):
    cost=0.0
    short_side=math.copysign(1,float(short['visual_value'])-float(short['host_value']))
    neighbor_side=math.copysign(1,float(neighbor['visual_value'])-float(neighbor['host_value']))
    if short_side==neighbor_side:cost-=5
    if short['semantic_type']==neighbor['semantic_type']:cost-=2
    if short.get('visual_subject') and short.get('visual_subject')==neighbor.get('visual_subject'):cost-=2
    if combined_seconds>float(rules['durations']['normal_max']):cost+=combined_seconds
    cost+=neighbor['duration']*.02
    return cost


def _value_inputs(item):
    stored=item.get('value_weighting')
    if stored:return copy.deepcopy(stored)
    return [{'candidate_ids':copy.deepcopy(item.get('candidate_ids',[])),
             'duration':float(item['duration']),
             'visual_value':float(item['visual_value']),'host_value':float(item['host_value']),
             'visual_value_breakdown':copy.deepcopy(item.get('visual_value_breakdown',[])),
             'host_value_breakdown':copy.deepcopy(item.get('host_value_breakdown',[]))}]


def _weighted_value_details(inputs, value_name):
    total=sum(float(item['duration']) for item in inputs)
    if total<=0:return 0.0,[]
    value=round(sum(float(item[value_name])*float(item['duration']) for item in inputs)/total,3)
    weighted={};order=[]
    for item in inputs:
        weight=float(item['duration'])/total
        for part in item.get(value_name+'_breakdown',[]):
            rule=part['rule']
            if rule not in weighted:weighted[rule]=0.0;order.append(rule)
            weighted[rule]+=float(part['value'])*weight
    breakdown=[{'rule':rule,'value':round(weighted[rule],3)} for rule in order]
    return value,breakdown


def _semantic_children(item):
    if item.get('children'):return copy.deepcopy(item['children'])
    keys=('candidate_ids','text','start','end','duration','semantic_type','visual_subject',
          'importance','emotion','visual_value','host_value','visual_value_breakdown','host_value_breakdown')
    return [{key:copy.deepcopy(item.get(key)) for key in keys}]


def _best_visual_child(item):
    children=_semantic_children(item)
    return max(children,key=lambda child:(searchable_visual_subject(child.get('visual_subject')),
        float(child.get('visual_value',0)),float(child.get('visual_value',0))-float(child.get('host_value',0)),
        len(str(child.get('visual_subject',''))),-float(child.get('duration',0))))


def merge_short_narratives(items, rules, duration=None, target_ratio=None):
    output=copy.deepcopy(items);minimum=float(rules['durations']['min_shot'])
    while len(output)>1:
        index=next((i for i,item in enumerate(output) if item['duration']<minimum),None)
        if index is None:break
        choices=[]
        for other in (index-1,index+1):
            if 0<=other<len(output):
                lo=min(index,other);hi=max(index,other);combined=round(output[hi]['end']-output[lo]['start'],3)
                choices.append((_merge_cost(output[index],output[other],combined,rules),other))
        _,other=min(choices,key=lambda value:(value[0],abs(value[1]-index)))
        lo=min(index,other);hi=max(index,other);left,right=output[lo],output[hi]
        dominant=left if left['duration']>=right['duration'] else right
        value_inputs=_value_inputs(left)+_value_inputs(right)
        visual,visual_breakdown=_weighted_value_details(value_inputs,'visual_value')
        host,host_breakdown=_weighted_value_details(value_inputs,'host_value')
        semantic_types=[]
        for source in (left,right):
            for semantic in source.get('merged_semantic_types') or [source['semantic_type']]:
                if semantic not in semantic_types:semantic_types.append(semantic)
        merged={**copy.deepcopy(dominant),'id':uuid.uuid4().hex[:10],
                'candidate_ids':left['candidate_ids']+right['candidate_ids'],
                'text':left['text']+right['text'],'start':left['start'],'end':right['end'],
                'duration':round(right['end']-left['start'],3),
                'visual_value':visual,'host_value':host,
                'visual_value_breakdown':visual_breakdown,'host_value_breakdown':host_breakdown,
                'value_weighting':value_inputs,'children':_semantic_children(left)+_semantic_children(right),
                'merged_semantic_types':semantic_types,
                'merge_reason':'短句按各自实际时长加权合并双价值'}
        visual_source=_best_visual_child(merged)
        merged['visual_source']={key:copy.deepcopy(visual_source.get(key)) for key in
                                 ('candidate_ids','text','semantic_type','visual_subject','visual_value','host_value')}
        output[lo:hi+1]=[merged]
    if duration is not None and target_ratio is not None:
        output=_assign_kinds_by_semantic_flow(output,rules)
        for item in output:
            if item.get('merge_reason'):item['decision_reason']+='；'+item['merge_reason']
    for item in output:item['id']='n-'+uuid.uuid4().hex[:10]
    return output


def refine_directional_boundaries(items, silences, rules):
    """Delay only B->A cuts until the outgoing word has audibly released.

    The semantic decision is already complete when this runs.  A->B
    boundaries intentionally remain untouched: letting narration continue over
    an incoming cutaway is editorially natural, while revealing the host before
    the last B-roll-covered syllable ends exposes a lip-sync mismatch.
    """
    output=copy.deepcopy(items);cfg=rules.get('directional_cuts',{}).get('broll_to_aroll',{})
    if not cfg.get('enabled',False) or len(output)<2:return output
    search_before=float(cfg.get('search_before_seconds',.04))
    search_after=float(cfg.get('search_after_seconds',.35))
    release=float(cfg.get('release_guard_seconds',.067))
    fallback=float(cfg.get('fallback_guard_seconds',.067))
    minimum=float(rules['durations']['min_shot'])
    normalized=sorted((float(s['start']),float(s['end'])) for s in silences
                      if float(s['end'])>float(s['start']))
    for index in range(len(output)-1):
        left,right=output[index],output[index+1]
        if left['kind']!='B' or right['kind']!='A':continue
        boundary=round(float(left['end']),3);source='fallback'
        cut=None
        for silence_start,silence_end in normalized:
            if silence_end<boundary-search_before:continue
            if silence_start>boundary+search_after:break
            if silence_start<=boundary<=silence_end:
                # The semantic timestamp is already inside a stable quiet area.
                cut=boundary;source='existing_silence';break
            if boundary<silence_start<=boundary+search_after:
                latest=silence_end-release
                cut=min(silence_start+release,latest) if latest>silence_start else (silence_start+silence_end)/2
                source='silence';break
        if cut is None:cut=boundary+fallback
        latest=min(boundary+search_after,float(right['end'])-minimum)
        cut=round(max(boundary,min(cut,latest)),3)
        if cut<=boundary+.001:continue
        adjustment={'type':'broll_to_aroll_release','original':boundary,'adjusted':cut,
                    'shift':round(cut-boundary,3),'source':source}
        left['end']=cut;left['duration']=round(cut-float(left['start']),3)
        right['start']=cut;right['duration']=round(float(right['end'])-cut,3)
        left['timing_adjustment']=copy.deepcopy(adjustment)
        right['timing_adjustment']=copy.deepcopy(adjustment)
    return output


def _balanced_cuts(start,end,count,candidates,minimum):
    if count<=1:return [start,end]
    available=sorted({float(c['start']) for c in candidates if start+minimum<=float(c['start'])<=end-minimum})
    cuts=[start]
    for part in range(1,count):
        remaining=count-part;low=cuts[-1]+minimum;high=end-remaining*minimum
        target=start+(end-start)*part/count
        choices=[value for value in available if low<=value<=high and value not in cuts]
        cut=min(choices,key=lambda value:abs(value-target)) if choices else target
        cuts.append(round(max(low,min(high,cut)),3))
    cuts.append(end)
    return cuts


def _shot_count(kind,seconds,rules,visual_role=None):
    dur=rules['durations']
    if kind=='A':return 1
    role_cfg=(dur.get('visual_roles') or {}).get(str(visual_role or '').upper())
    if role_cfg:
        maximum=float(role_cfg.get('max',dur['broll_single_max']))
        target=float(role_cfg.get('target',dur['broll_target']))
        return 1 if seconds<=maximum else max(1,math.ceil(round(seconds/target,9)))
    if seconds<=float(dur['broll_single_max']):return 1
    if seconds<=float(dur['broll_two_shot_max']):return 2
    if seconds<=float(dur['broll_three_shot_max']):return 3
    return math.ceil(seconds/float(dur['broll_target']))


def _fallback_query(text,semantic):
    patterns=((r'北京|上海|香港|城市|街道','city street'),(r'火车|地铁|飞机|船|出行','travel transportation'),
              (r'书|阅读|笔记','person reading book'),(r'手机|视频|信息','person using smartphone'),
              (r'工作|办公|公司','person working at desk'),(r'钱|消费|存款','counting money'),
              (r'历史|年代|过去','historical archive'),(r'数据|统计|百分比|年份','data chart'))
    for pattern,query in patterns:
        if re.search(pattern,text):return query
    return {'person':'person portrait','location':'city landscape','object':'object close up','event':'people event',
            'action':'person activity','process':'work process','history':'historical archive','data':'data chart'}.get(semantic,'documentary lifestyle')


def visual_queries(item):
    item=item.get('visual_source') or _best_visual_child(item)
    values=[]
    if searchable_visual_subject(item.get('visual_subject')):values.append(item['visual_subject'])
    fallback=_fallback_query(item['text'],item['semantic_type'])
    if fallback not in values:values.append(fallback)
    return values[:3]


def _theme_key(item):
    source=item.get('visual_source') or _best_visual_child(item)
    subject=re.sub(r'\W','',str(source.get('visual_subject','')).lower())
    return subject or source['semantic_type']


def build_visual_shots(narratives, candidates, rules, semantics=None, aroll_provider=None):
    spans=[]
    for narrative in narratives:
        if (spans and spans[-1]['kind']==narrative['kind'] and
            spans[-1].get('visual_role')==narrative.get('visual_role') and
            (narrative['kind']=='A' or spans[-1]['theme']==_theme_key(narrative))):
            spans[-1]['items'].append(narrative);spans[-1]['end']=narrative['end']
        else:
            spans.append({'kind':narrative['kind'],'visual_role':narrative.get('visual_role'),
                          'theme':_theme_key(narrative),'start':narrative['start'],'end':narrative['end'],
                          'items':[narrative]})
    output=[]
    by_id={c['id']:c for c in candidates};minimum=float(rules['durations']['min_shot'])
    semantics=semantics or [{} for _ in candidates]
    duration=float(narratives[-1]['end'])
    candidate_ranges=[]
    for index,candidate in enumerate(candidates):
        candidate_start=0.0 if index==0 else float(candidate['start'])
        candidate_end=duration if index==len(candidates)-1 else float(candidates[index+1]['start'])
        candidate_ranges.append((candidate,candidate_start,candidate_end))
    for span in spans:
        seconds=round(span['end']-span['start'],3)
        if span['kind']=='A':
            selected_nodes=[]
            cuts=[span['start'],span['end']]
        else:
            count=_shot_count(span['kind'],seconds,rules,span.get('visual_role'));selected_nodes=[]
            cuts=_balanced_cuts(span['start'],span['end'],count,candidates,minimum)
        boundary_by_time={node['at']:node for node in selected_nodes}
        for part,(start,end) in enumerate(zip(cuts,cuts[1:]),1):
            covered=[n for n in span['items'] if n['end']>start+.001 and n['start']<end-.001]
            allowed_ids={candidate_id for narrative in covered for candidate_id in narrative['candidate_ids']}
            candidate_ids=[candidate['id'] for candidate,candidate_start,candidate_end in candidate_ranges
                           if candidate['id'] in allowed_ids and candidate_end>start+.001 and candidate_start<end-.001]
            if not candidate_ids:
                candidate_ids=[candidate['id'] for candidate in candidates if candidate['id'] in allowed_ids]
            source=max(covered,key=lambda n:min(end,n['end'])-max(start,n['start']))
            material_source=(source.get('visual_source') or _best_visual_child(source)) if span['kind']=='B' else source
            unit_text=''.join(by_id[i]['text'] for i in candidate_ids if i in by_id) or source['text']
            shot={'id':uuid.uuid4().hex[:10],'narrative_ids':[n['id'] for n in covered],
                  'from':min(candidate_ids),'to':max(candidate_ids),'start':round(start,3),'end':round(end,3),
                  'kind':span['kind'],'text':unit_text,'semantic_type':source['semantic_type'],
                  'visual_segment_id':source.get('visual_segment_id') or source.get('id'),
                  'visual_role':span.get('visual_role') or ('A' if span['kind']=='A' else None),
                  'legacy_roll_type':span['kind'],
                  'visual_subject':material_source.get('visual_subject',''),'importance':source['importance'],'emotion':source['emotion'],
                  'visual_value':source['visual_value'],'host_value':source['host_value'],
                  'visual_value_breakdown':source['visual_value_breakdown'],'host_value_breakdown':source['host_value_breakdown'],
                  'title':material_source.get('visual_subject') or material_source.get('text','')[:30] or ('人物出镜' if span['kind']=='A' else '辅助画面'),
                  'reason':source['decision_reason'],'asset':None,'candidates':[],'source':None,'media_start':0,
                  'material_status':'pending' if span['kind']=='B' else 'host','visual_part':part,'visual_parts':len(cuts)-1}
            if span['kind']=='A':
                boundary=boundary_by_time.get(round(start,3));shot['cut_score']=boundary['score'] if boundary else None
                shot['cut_reason']=' / '.join(boundary['reasons']) if boundary else ''
                if aroll_provider=='autodl_h3':
                    shot['editorial_review']=('连续 A-roll 超过 15 秒：生成时按最少段数拆成不超过 15 秒的 H3 片段，'
                                              '片段之间使用程序硬切' if seconds>15 else None)
                    shot['camera']=None;shot['motion']=None;shot['visual_change']='h3_native'
                    shot['aroll_edit_mode']='provider_native';shot['keywords']=[]
                else:
                    shot['editorial_review']=None
                    shot['camera']='medium';shot['motion']=None
                    shot['visual_change']='hold';shot['aroll_edit_mode']='semantic_continuous';shot['keywords']=[]
            else:
                shot['camera']=None;shot['motion']=None
                shot['visual_change']='broll' if not span.get('visual_role') else str(span.get('visual_role')).lower()
                query=source.get('stock_search_query') or source.get('search_query')
                shot['keywords']=[query] if query else visual_queries(source)
                for key in ('entities','evidence_required','evidence_target','search_query','fallback',
                            'stock_search_query','stock_search_query_alt',
                            'recording_required','recording_instruction','motion_type',
                            'generation_concept'):
                    if key in source:shot[key]=copy.deepcopy(source.get(key))
            output.append(shot)
    return output


def build_timeline_from_visual_plan(candidates, segments, duration, rules, silences=None, aroll_provider=None):
    """Build internal visual shots from macro Visual Master Plan segments."""
    candidates=copy.deepcopy(candidates);by_id={c['id']:c for c in candidates}
    narratives=[]
    importance_map={1:'low',2:'low',3:'normal',4:'high',5:'high'}
    for item in segments:
        ids=[value for value in item.get('candidate_ids',[]) if value in by_id]
        if not ids:continue
        child_units=[copy.deepcopy(by_id[value]) for value in ids]
        semantic={
            'id':item.get('id'),
            'text':item.get('text') or ''.join(unit['text'] for unit in child_units),
            'semantic_type':item.get('semantic_type') or 'other',
            'visual_subject':item.get('visual_subject') or '',
            'importance':importance_map.get(int(item.get('importance') or 3),'normal'),
            'emotion':item.get('emotion') or 'neutral',
        }
        visual,host,visual_breakdown,host_breakdown=value_candidate(semantic,rules)
        role=str(item.get('visual_role') or 'A').upper()
        kind='A' if role=='A' else 'B'
        narrative={
            **copy.deepcopy(item),
            'id':item.get('id'),
            'candidate_ids':ids,
            'children':child_units,
            'start':round(float(item['start']),3),
            'end':round(float(item['end']),3),
            'duration':round(float(item['end'])-float(item['start']),3),
            'semantic_type':semantic['semantic_type'],
            'visual_subject':semantic['visual_subject'],
            'importance':semantic['importance'],
            'emotion':semantic['emotion'],
            'visual_role':role,
            'kind':kind,
            'visual_value':visual,
            'host_value':host,
            'visual_value_breakdown':visual_breakdown,
            'host_value_breakdown':host_breakdown,
            'decision_reason':item.get('reason') or f'视觉导演判定为 {role}',
        }
        narrative['visual_source']={
            key:copy.deepcopy(narrative.get(key))
            for key in ('candidate_ids','text','semantic_type','visual_subject','visual_value','host_value')
        }
        narratives.append(narrative)
    if silences is not None:
        narratives=refine_directional_boundaries(narratives,silences,rules)
    shots=build_visual_shots(narratives,candidates,rules,None,aroll_provider)
    return narratives,shots


def build_timeline(candidates, semantics, duration, target_ratio, rules, silences=None, aroll_provider=None):
    # Short phrases are merged first, then A/B is chosen from semantic values
    # and the surrounding strong semantic passage.  target_ratio is accepted
    # only for compatibility with older projects and is intentionally ignored.
    classified=classify_candidates(candidates,semantics,duration,target_ratio,rules,assign=False)
    narratives=merge_short_narratives(classified,rules,duration,target_ratio)
    if silences is not None:narratives=refine_directional_boundaries(narratives,silences,rules)
    shots=build_visual_shots(narratives,candidates,rules,semantics,aroll_provider)
    return narratives,shots
