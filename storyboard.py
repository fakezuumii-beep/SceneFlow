"""Deterministic semantic-to-visual storyboard rules.

The LLM classifies candidate text only.  This module owns A/B selection,
duration merging, visual shot count, natural timing cuts, and continuity repair.
"""
from __future__ import annotations

import copy
import hashlib
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
              'host_return','durations','anchors','directional_cuts','camera_choices','aroll_variation')
    if any(key not in rules for key in required):raise ValueError('分镜规则配置不完整')
    if len(set(rules['semantic_types']))!=len(rules['semantic_types']):raise ValueError('分镜语义类型配置重复')
    if not rules['camera_choices']:raise ValueError('A-roll 景别配置不能为空')
    tiers=rules['aroll_variation'].get('tiers',[])
    if not tiers or tiers[-1].get('max_seconds') is not None:raise ValueError('A-roll 时长分层必须包含无上限档')
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


def _optional_identity(item):
    ids=','.join(str(value) for value in item.get('candidate_ids',[]))
    return ids+'|'+str(item.get('text',''))


def _choose_optional_broll(output, optional, needed_seconds, rules):
    """Choose an episode-wide subset closest to target, then prefer visual value.

    Dynamic programming is quantized only for subset search.  The winning ratio
    and every reported duration continue to use the original audio timestamps.
    Sorting by semantic value and stable identity removes appearance-order bias.
    """
    if not optional or needed_seconds<=0:return set()
    quantum=max(.01,float(rules['selection']['ratio_quantum_seconds']))
    ranked=sorted(optional,key=lambda index:(
        -(float(output[index]['visual_value'])-float(output[index]['host_value'])),
        -float(output[index]['visual_value']),float(output[index]['host_value']),
        _optional_identity(output[index])))
    durations=[max(1,round(float(output[index]['duration'])/quantum)) for index in ranked]
    target=max(0,round(float(needed_seconds)/quantum))
    limit=target+(max(durations) if durations else 0)
    # tick -> ((visual-host gain, visual gain, negative host cost), bit mask)
    states={0:((0.0,0.0,0.0),0)}
    for rank,(index,ticks) in enumerate(zip(ranked,durations)):
        item=output[index];seconds=float(item['duration'])
        contribution=((float(item['visual_value'])-float(item['host_value']))*seconds,
                      float(item['visual_value'])*seconds,-float(item['host_value'])*seconds)
        additions={}
        for total,(quality,mask) in states.items():
            combined=total+ticks
            if combined>limit:continue
            candidate=(tuple(a+b for a,b in zip(quality,contribution)),mask|(1<<rank))
            previous=additions.get(combined) or states.get(combined)
            if previous is None or candidate[0]>previous[0] or (candidate[0]==previous[0] and candidate[1]<previous[1]):
                additions[combined]=candidate
        for total,candidate in additions.items():
            previous=states.get(total)
            if previous is None or candidate[0]>previous[0] or (candidate[0]==previous[0] and candidate[1]<previous[1]):
                states[total]=candidate
    winning_total,(quality,mask)=min(states.items(),key=lambda entry:(
        abs(entry[0]-target),-entry[1][0][0],-entry[1][0][1],-entry[1][0][2],entry[0],entry[1][1]))
    return {index for rank,index in enumerate(ranked) if mask&(1<<rank)}


def _assign_kinds_by_ratio(items, duration, target_ratio, rules):
    """Assign A/B from dual values plus one episode-wide ratio optimization."""
    output=copy.deepcopy(items);selection=rules['selection']
    definite_b=float(selection['definite_b_advantage']);definite_a=float(selection['definite_a_advantage'])
    target=max(0.0,min(100.0,float(target_ratio)));episode=max(float(duration),.001)
    opening=bool(rules.get('anchors',{}).get('opening_aroll'))
    closing=bool(rules.get('anchors',{}).get('closing_aroll'))
    optional=[]
    for index,item in enumerate(output):
        visual=float(item['visual_value']);host=float(item['host_value']);advantage=round(visual-host,3)
        item['value_advantage']=advantage
        anchor=(index==0 and opening) or (index==len(output)-1 and closing)
        if anchor:
            item['kind']='A';item['decision_reason']='程序开场锚点保留人物' if index==0 else '程序结尾锚点回到人物'
        elif advantage<=definite_a:
            item['kind']='A';item['decision_reason']=f'视觉价值 {visual:g} / 人物价值 {host:g}，人物优势明确，判为 A-roll'
        elif advantage>=definite_b:
            item['kind']='B';item['decision_reason']=f'视觉价值 {visual:g} / 人物价值 {host:g}，画面优势明确，判为 B-roll'
        else:
            item['kind']=None;optional.append(index)
    b_seconds=sum(float(item['duration']) for item in output if item['kind']=='B')
    selected=_choose_optional_broll(output,optional,episode*target/100-b_seconds,rules)
    for index in optional:
        item=output[index];item['kind']='B' if index in selected else 'A'
        if index in selected:b_seconds+=float(item['duration'])
    final_ratio=100*b_seconds/episode
    for index in optional:
        item=output[index]
        item['decision_reason']=(f'视觉价值 {float(item["visual_value"]):g} / 人物价值 {float(item["host_value"]):g}，'
                                 f'进入全片候选池；为接近 B-roll {target:g}% 目标（分配后 {final_ratio:.1f}%），'
                                 f'选择 {item["kind"]}-roll')
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
    return _assign_kinds_by_ratio(result,duration,target_ratio,rules) if assign else result


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
        output=_assign_kinds_by_ratio(output,duration,target_ratio,rules)
        for item in output:
            if item.get('merge_reason'):item['decision_reason']+='；'+item['merge_reason']
    for item in output:item['id']='n-'+uuid.uuid4().hex[:10]
    return output


def _runs(items,kind):
    runs=[];index=0
    while index<len(items):
        if items[index]['kind']!=kind:index+=1;continue
        end=index
        while end+1<len(items) and items[end+1]['kind']==kind:end+=1
        runs.append((index,end,round(items[end]['end']-items[index]['start'],3)));index=end+1
    return runs


def repair_continuity(items, rules):
    """Return to the host only at a strong natural semantic node.

    No elapsed-time cooldown is used.  A long run without a sufficiently
    valuable internal host node remains B-roll instead of receiving a forced,
    mechanical A-roll cut.
    """
    output=copy.deepcopy(items);cfg=rules['host_return']
    minimum_items=int(cfg['minimum_broll_narratives']);minimum_host=float(cfg['minimum_host_value'])
    while True:
        changed=False
        for first,last,_ in _runs(output,'B'):
            if last-first+1<minimum_items:continue
            middle=range(first+1,last)
            candidates=[i for i in middle if float(output[i]['host_value'])>=minimum_host
                        and float(output[i]['host_value'])>float(output[i]['visual_value'])]
            if not candidates:continue
            center=(float(output[first]['start'])+float(output[last]['end']))/2
            index=min(candidates,key=lambda i:(-float(output[i]['host_value']),
                      float(output[i]['visual_value']),abs((float(output[i]['start'])+float(output[i]['end']))/2-center),
                      _optional_identity(output[i])))
            output[index]['kind']='A'
            output[index]['decision_reason']=(f'连续 B-roll 中出现自然人物节点：人物价值 {float(output[index]["host_value"]):g} '
                                              f'高于视觉价值 {float(output[index]["visual_value"]):g}，回到主持人')
            changed=True;break
        if not changed:break
    return output


def refine_directional_boundaries(items, silences, rules):
    """Delay only B->A cuts until the outgoing word has audibly released.

    The semantic/ratio decision is already complete when this runs.  A->B
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


def _leading_subject(text):
    text=re.sub(r'^[\s“”"\'「」【】]+','',str(text or ''))
    text=re.sub(r'^(?:但是|不过|然而|所以|因此|另外|同时|其实|换句话说)[，,\s]*','',text)
    pronoun=re.match(r'^(我们|你们|他们|她们|它们|大家|人们|我|你|他|她|它)(?=[是在会有把将认为发现需要开始成为也又却，,])',text)
    if pronoun:return pronoun.group(1)
    noun=re.match(r'^([\w\u3400-\u9fff]{2,8}?)(?=是|在|会|有|把|将|认为|发现|需要|开始|成为)',text)
    return noun.group(1) if noun else ''


def semantic_cut_nodes(candidates, semantics, start, end, rules):
    """Score real transcript boundaries; time balance is never a cut source."""
    cfg=rules['aroll_variation'];weights=cfg['cut_weights'];minimum=float(cfg['minimum_change_gap'])
    transition=tuple(cfg.get('transition_words',[]));viewpoint=tuple(cfg.get('viewpoint_words',[]))
    nodes=[]
    for index in range(1,len(candidates)):
        at=round(float(candidates[index]['start']),3)
        if at<start+minimum or at>end-minimum:continue
        previous,current=candidates[index-1],candidates[index]
        before=str(previous.get('text','')).rstrip();after=str(current.get('text','')).lstrip()
        pause=max(0.0,float(current.get('start',at))-float(previous.get('end',at)))
        score=0.0;reasons=[]
        if pause>=float(cfg['strong_pause_seconds']):score+=float(weights['strong_pause']);reasons.append('明显停顿')
        elif pause>=float(cfg['pause_seconds']):score+=float(weights['pause']);reasons.append('停顿')
        if re.search(r'[。！？!?]”?[\s]*$',before):score+=float(weights['sentence_end']);reasons.append('完整句结束')
        elif re.search(r'[；;：:][\s]*$',before):score+=float(weights['clause_end']);reasons.append('分句结束')
        elif re.search(r'[，,][\s]*$',before):score+=float(weights['comma']);reasons.append('逗号')
        stripped=re.sub(r'^[“”"\'「」【】\s]+','',after)
        if any(stripped.startswith(word) for word in transition):score+=float(weights['transition']);reasons.append('转折或承接词')
        if any(stripped.startswith(word) for word in viewpoint):score+=float(weights['viewpoint']);reasons.append('新观点开始')
        previous_semantic=semantics[index-1] if index-1<len(semantics) else {}
        current_semantic=semantics[index] if index<len(semantics) else {}
        if previous_semantic.get('semantic_type')!=current_semantic.get('semantic_type'):
            score+=float(weights['semantic_change']);reasons.append('语义类型变化')
        left_subject,right_subject=_leading_subject(before),_leading_subject(after)
        if left_subject and right_subject and left_subject!=right_subject:
            score+=float(weights['subject_change']);reasons.append('主语变化')
        left_visual=str(previous_semantic.get('visual_subject','')).strip()
        right_visual=str(current_semantic.get('visual_subject','')).strip()
        if left_visual and right_visual and left_visual!=right_visual:
            score+=float(weights['viewpoint']);reasons.append('可视主体变化')
        nodes.append({'at':at,'score':round(score,3),'reasons':list(dict.fromkeys(reasons)),'candidate_index':index})
    return nodes


def _change_limits(seconds,rules):
    cfg=rules['aroll_variation']
    for tier in cfg['tiers']:
        maximum=tier.get('max_seconds')
        if maximum is None or seconds<=float(maximum):
            minimum=int(tier.get('min_changes',0));configured=tier.get('max_changes')
            maximum_changes=(max(minimum,math.ceil(seconds/float(cfg['long_change_target_seconds']))-1)
                             if configured is None else int(configured))
            return minimum,maximum_changes
    return 0,0


def _select_semantic_cuts(nodes,seconds,rules):
    minimum,maximum=_change_limits(seconds,rules);cfg=rules['aroll_variation']
    if maximum<=0:return []
    preferred=[node for node in nodes if node['score']>=float(cfg['preferred_cut_score'])]
    fallback=[node for node in nodes if node['score']>=float(cfg['fallback_cut_score'])]
    desired=min(maximum,max(minimum,len(preferred)))
    if minimum==0 and not preferred:return []
    pool=preferred if len(preferred)>=desired else fallback
    selected=[];gap=float(cfg['minimum_change_gap'])
    start=min(node['at'] for node in nodes)-gap if nodes else 0;end=max(node['at'] for node in nodes)+gap if nodes else seconds
    targets=[start+(end-start)*(slot+1)/(desired+1) for slot in range(desired)]
    for target in targets:
        available=[node for node in pool if node not in selected and all(abs(node['at']-chosen['at'])>=gap for chosen in selected)]
        if not available:break
        # Semantic strength is primary; distance is only a tie-breaker between
        # equally meaningful boundaries.
        selected.append(min(available,key=lambda item:(-item['score'],abs(item['at']-target),item['at'])))
    return sorted(selected,key=lambda item:item['at'])


def _stable_choice(options,key):
    if not options:return 'hold'
    value=int(hashlib.sha256(str(key).encode('utf-8')).hexdigest()[:12],16)
    return options[value%len(options)]


def _initial_camera(source,key,rules):
    if source.get('semantic_type') in ('hook','emotion','question','summary') or source.get('importance')=='high':return 'medium_close'
    return _stable_choice(rules['camera_choices'],key)


def _choose_aroll_change(source,previous_camera,previous_action,key):
    semantic=source.get('semantic_type');options=[]
    if semantic in ('hook','emotion','question','summary'):
        options+=['push_in','cut_in','push_in']
    elif semantic in ('transition','intro'):
        options+=['cut_out','pull_out','cut_out']
    else:
        options+=['cut_in','cut_out','push_in','pull_out']
    if previous_camera=='medium':
        options=[x for x in options if x not in ('cut_out','pull_out')]
        if not options:options=['push_in','cut_in']
    elif previous_camera=='close':
        options=[x for x in options if x not in ('cut_in','push_in')]
        if not options:options=['pull_out','cut_out']
    alternatives=[x for x in options if x!=previous_action]
    return _stable_choice(alternatives or options,key)


def _shot_count(kind,seconds,rules):
    dur=rules['durations']
    if kind=='A':return 1
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


def build_visual_shots(narratives, candidates, rules, semantics=None):
    spans=[]
    for narrative in narratives:
        if (spans and spans[-1]['kind']==narrative['kind'] and
            (narrative['kind']=='A' or spans[-1]['theme']==_theme_key(narrative))):
            spans[-1]['items'].append(narrative);spans[-1]['end']=narrative['end']
        else:
            spans.append({'kind':narrative['kind'],'theme':_theme_key(narrative),'start':narrative['start'],'end':narrative['end'],'items':[narrative]})
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
            nodes=semantic_cut_nodes(candidates,semantics,span['start'],span['end'],rules)
            selected_nodes=_select_semantic_cuts(nodes,seconds,rules)
            cuts=[span['start']]+[node['at'] for node in selected_nodes]+[span['end']]
        else:
            count=_shot_count(span['kind'],seconds,rules);selected_nodes=[]
            cuts=_balanced_cuts(span['start'],span['end'],count,candidates,minimum)
        boundary_by_time={node['at']:node for node in selected_nodes}
        span_key='|'.join([str(span['start']),str(span['end'])]+[item['text'] for item in span['items']])
        current_camera=None;previous_action='hold';previous_kind=None
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
                  'visual_subject':material_source.get('visual_subject',''),'importance':source['importance'],'emotion':source['emotion'],
                  'visual_value':source['visual_value'],'host_value':source['host_value'],
                  'visual_value_breakdown':source['visual_value_breakdown'],'host_value_breakdown':source['host_value_breakdown'],
                  'title':material_source.get('visual_subject') or material_source.get('text','')[:30] or ('人物出镜' if span['kind']=='A' else '辅助画面'),
                  'reason':source['decision_reason'],'asset':None,'candidates':[],'source':None,'media_start':0,
                  'material_status':'pending' if span['kind']=='B' else 'host','visual_part':part,'visual_parts':len(cuts)-1}
            if span['kind']=='A':
                boundary=boundary_by_time.get(round(start,3));shot['cut_score']=boundary['score'] if boundary else None
                shot['cut_reason']=' / '.join(boundary['reasons']) if boundary else ''
                required_changes,_=_change_limits(seconds,rules)
                long_semantic=any(float(item['end'])-float(item['start'])>18 for item in span['items'])
                missing_nodes=seconds>18 and len(selected_nodes)<required_changes
                shot['editorial_review']=('A-roll 语义段超过 18 秒，建议先复查语义边界' if long_semantic else
                                          'A-roll 超过 18 秒但缺少足够自然切点，已避免数学硬切' if missing_nodes else None)
                if part==1:
                    current_camera='medium' if len(cuts)==2 else _initial_camera(source,span_key,rules);action='hold'
                elif previous_kind=='B':
                    action='return_primary';current_camera=_initial_camera(source,span_key+'|return|'+str(part),rules)
                else:
                    action=_choose_aroll_change(source,current_camera,previous_action,span_key+'|'+str(start))
                if action=='cut_in':current_camera='medium_close' if current_camera=='medium' else 'close'
                elif action=='cut_out':current_camera='medium' if current_camera=='medium_close' else 'medium_close'
                shot['camera']=current_camera;shot['motion']=action if action in ('push_in','pull_out') else None
                shot['visual_change']=action;shot['keywords']=[]
                previous_action=action;previous_kind=shot['kind']
            else:
                shot['camera']=None;shot['motion']=None;shot['visual_change']='broll';shot['keywords']=visual_queries(source)
            output.append(shot)
    return output


def build_timeline(candidates, semantics, duration, target_ratio, rules, silences=None):
    # Short segments are merged before the one and only episode-wide A/B
    # allocation, so a provisional early decision cannot influence the final
    # optional pool or recreate appearance-order bias through merge direction.
    classified=classify_candidates(candidates,semantics,duration,target_ratio,rules,assign=False)
    narratives=repair_continuity(merge_short_narratives(classified,rules,duration,target_ratio),rules)
    if silences is not None:narratives=refine_directional_boundaries(narratives,silences,rules)
    shots=build_visual_shots(narratives,candidates,rules,semantics)
    return narratives,shots
