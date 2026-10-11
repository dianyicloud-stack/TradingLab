"""Offline before/after budget accounting from immutable task captures. No HTTP."""
from pathlib import Path
import ast,importlib.util,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engines.live.advisory import PROMPT
from engines.live.evidence import build,encoded,estimate,digest,measure,unique
from adapters.ai.request_guard import RequestGuard
import httpx
OUT=ROOT/'artifacts/input_budget_20260918'
SCHEMA=json.loads((ROOT/'contracts/live/advisory_opinion_1.0.json').read_text(encoding='utf-8'))

def load(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def run_old(frozen):
    path=OUT/'before/engines/live/evidence.py';spec=importlib.util.spec_from_file_location('captured_evidence_v2',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=path.read_text(encoding='utf-8').splitlines();rounds=[]
    def trace(frame,event,arg):
        if event=='line' and frame.f_code.co_filename==str(path) and source[frame.f_lineno-1].lstrip().startswith('if tokens<=target:'):
            v=frame.f_locals
            if rounds and rounds[-1]['minutes']==v['minutes']:return trace
            e=v['evidence'];rounds.append({'minutes':v['minutes'],'estimated_input_tokens':v['tokens'],
                'evidence_bytes':len(encoded(e).encode()),'components':{k:measure(value) for k,value in e.items()},
                'snapshot_components':{k:measure(value) for k,value in e['snapshot_path'].items()}})
        return trace
    sys.settrace(trace)
    try:_,meta=module.build(frozen,PROMPT,SCHEMA,target=32768);status='PASS'
    except Exception as error:status=getattr(error,'code',type(error).__name__);meta=None
    finally:sys.settrace(None)
    return {'status':status,'rounds':rounds,'metadata':meta}

def main():
    # The prompt/schema are unchanged; do not recreate the user's past model input from a later prompt.
    tree=ast.parse((OUT/'before/engines/live/advisory.py').read_text(encoding='utf-8'))
    old_prompt=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROMPT' for t in n.targets))
    assert old_prompt==PROMPT
    assert SCHEMA==json.loads((OUT/'before/contracts/live/advisory_opinion_1.0.json').read_text(encoding='utf-8'))
    provider=load('private/sz300474-provider.json')
    recorded=next(r['payload'] for r in provider if r['kind']=='HTTP_REQUEST');template=json.loads(recorded['request_body'])
    policy=json.loads(template['input'])['action_policy'];samples=[]
    for symbol in ('bj920161','sh688601','sz300474','sh688601-later'):
        task=load(f'private/{symbol}.json');f=task['frozen'];before=run_old(f)
        recovered=load(f"private/{symbol.removesuffix('-later')}-baselines.json")
        assert not recovered['missing']
        augmented={**f,'comparison_observations':recovered['observations']}
        augmented['input_hash']=digest({k:v for k,v in augmented.items() if k not in ('input_id','input_hash')});augmented['input_id']='ADVIN-'+augmented['input_hash'][:32]
        e,m=build(augmented,PROMPT,SCHEMA,target=32768)
        body={**template,'input':encoded({**e,'action_policy':policy})};guard=RequestGuard(m)
        guard.before(httpx.Request('POST','https://api.deepseek.com/responses',content=encoded(body).encode()))
        rows=f['incremental_evidence']['observations'];events=f['incremental_evidence']['events'];ctx=f['context_evidence'];all_rows=rows+events+ctx['observations']+ctx['events']+recovered['observations']
        refs=[r for c in f.get('evidence_validation',{}).get('events',[]) for r in c.get('evidence_refs',[])]
        counts={'candidate_incremental_observations':len(rows),'dedup_incremental_observations':len(unique(rows)),
            'candidate_events':len(events),'dedup_events':len(unique(events)),
            'snapshots':sum(r.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1' for r in unique(rows)),
            'formal_observations':sum(r.get('source_format')!='V2A_RUNTIME_SNAPSHOT_V1' for r in unique(rows)),
            'context_observations':len(ctx['observations']),'context_events':len(ctx['events']),
            'validation_reference_occurrences':len(refs),'unique_validation_references':len(unique(refs)),
            'recovered_comparison_observations':len(recovered['observations']),
            'snapshot_summary_intervals':len(e['snapshot_path']['intervals']),'event_nearby_points':len(e['snapshot_path']['event_nearby_indices']),
            'crossings':len(e['snapshot_path']['crossings']),'quality_runs':len(e['snapshot_path']['quality_runs'])}
        result={'symbol':symbol,'request_id':next((r['request_id'] for r in load('capture.json')['samples'] if r['symbol']==symbol),None),
            'original_input_id':f['input_id'],'original_input_hash':f['input_hash'],'original_cutoff':f['data_through_at'],
            'previous_success_cutoff':(f.get('previous_advisory') or {}).get('data_through_at'),
            'settings':{k:task['settings'].get(k) for k in ('provider','model','reasoning_effort')},
            'counts':counts,'identities':{'symbols':sorted({r['symbol'] for r in all_rows if r.get('symbol')}),
                'sessions':sorted({r['tracking_session_id'] for r in all_rows if r.get('tracking_session_id')}),
                'dates':sorted({r['session_date'] for r in all_rows if r.get('session_date')}),
                'previous_has_nested_full_input':any(k in (f.get('previous_advisory') or {}) for k in ('frozen_input','incremental_evidence','context_evidence'))},
            'raw_component_sizes':{k:measure(v) for k,v in f.items()},'before':before,'after':m,
            'derived_input_id':augmented['input_id'],'derived_input_hash':augmented['input_hash'],
            'baseline_provenance':recovered['provenance'],
            'simulated_http_guard':{k:v for k,v in guard.records[0].items() if k not in ('request_body','created_at')},
            'http_sent':False}
        samples.append(result)
    output={'budget_configuration':load('process-budget.json'),
            'counting':'ceil(sum(ASCII character / 3, non-ASCII character * 1.5)); engineering estimate, not a model tokenizer or exact billing count',
            'prompt':{'utf8_bytes':len(PROMPT.encode()),'estimated_tokens':estimate(PROMPT)},'schema':measure(SCHEMA),
            'actual_success_http_components':{k:measure(v) for k,v in template.items() if k!='input'},
            'model':template['model'],'output_parameter_present':'max_output_tokens' in template,
            'existing_guard_output_reserve':393216,'existing_guard_context_byte_allowance':1048576-393216-16384,
            'output_reserve_source':'existing RequestGuard code; not a newly verified model specification',
            'budget_changed':False,'samples':samples,'real_provider_calls':0}
    (OUT/'budget-audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'symbol':r['symbol'],'counts':r['counts'],'before_rounds':[(x['minutes'],x['estimated_input_tokens']) for x in r['before']['rounds']],
        'after_tokens':r['after']['estimated_input_tokens'],'after_bytes':r['after']['evidence_bytes'],'after_minutes':r['after']['snapshot_interval_minutes'],
        'http_estimate':r['simulated_http_guard']['estimated_input_tokens']} for r in samples]))
if __name__=='__main__':main()
