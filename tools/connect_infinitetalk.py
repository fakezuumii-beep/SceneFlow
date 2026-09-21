"""Convert the user's single-speaker canvas to a private API copy and connect SOLO."""
import argparse, hashlib, json, shutil, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core


def convert(canvas):
    nodes={n['id']:n for n in canvas['nodes']};links={x[0]:x for x in canvas['links']}
    setters={n['widgets_values'][0]:n for n in nodes.values() if n['type']=='SetNode'}
    def resolve(link):
        _,origin,slot,*_=links[link];node=nodes[origin]
        if node['type']=='GetNode':return resolve(setters[node['widgets_values'][0]]['inputs'][0]['link'])
        if node['type']=='SetNode':return resolve(node['inputs'][0]['link'])
        return [str(origin),slot]
    graph={}
    for node in nodes.values():
        if node['type'] in ('SetNode','GetNode','Note','MarkdownNote'):continue
        values=node.get('widgets_values',[]);inputs={};cursor=0
        for item in node.get('inputs',[]):
            name=item['name']
            if item.get('widget'):
                value=values.get(name) if isinstance(values,dict) else values[cursor]
                cursor+=1
                if name=='seed' and isinstance(values,list) and cursor<len(values) and values[cursor] in ('fixed','randomize','increment','decrement'):cursor+=1
                if name not in ('upload','audioUI'):inputs[name]=value
            if item.get('link') is not None:inputs[name]=resolve(item['link'])
        graph[str(node['id'])]={'class_type':node['type'],'inputs':inputs}
    output=next(k for k,n in graph.items() if n['class_type']=='VHS_VideoCombine')
    needed=set()
    def visit(key):
        if key in needed:return
        needed.add(key)
        for value in graph[key]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in graph:visit(value[0])
    visit(output)
    graph={k:v for k,v in graph.items() if k in needed}
    for node in graph.values():
        if node['class_type']=='MultiTalkWav2VecEmbeds':node['inputs']['fps']=25
    graph[output]['inputs']['frame_rate']=25
    return graph


def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--url',default='http://127.0.0.1:8188');args=parser.parse_args()
    graph=convert(json.loads(args.source.read_text(encoding='utf-8-sig')))
    digest=hashlib.sha256(json.dumps(graph,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    folder=core.PRIVATE/'workflows';folder.mkdir(exist_ok=True)
    core.atomic_json(folder/(digest+'.json'),graph)
    settings=core.PRIVATE/'settings.json'
    if settings.exists():shutil.copy2(settings,core.PRIVATE/('settings-before-infinitetalk-'+time.strftime('%Y%m%d-%H%M%S')+'.json'))
    values={'aroll_provider':'infinitetalk','aroll_custom_type':'comfyui','aroll_comfyui_url':args.url,
            'aroll_comfyui_workflow':'workflows/'+digest+'.json','aroll_comfyui_workflow_hash':digest}
    for key,kind in (('aroll_person_node','LoadImage'),('aroll_audio_node','LoadAudio'),('aroll_output_node','VHS_VideoCombine')):
        values[key]=next(k for k,n in graph.items() if n['class_type']==kind)
    core.save_settings(values)
    print(json.dumps({'provider':'infinitetalk','nodes':len(graph),'workflow':values['aroll_comfyui_workflow']},ensure_ascii=False))


if __name__=='__main__':main()
