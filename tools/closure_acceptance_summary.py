"""Summarize saved evidence without mutating any runtime or claiming production PASS."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1];base=ROOT/'artifacts/m2_auto_agent_closure'
def read(path):return json.loads((base/path).read_text(encoding='utf-8-sig'))
log=(base/'c-regression-backlog-final.txt').read_text(encoding='utf-8',errors='replace')
match=re.search(r'Ran (\d+) tests in ([\d.]+)s',log)
soak=read('c-soak-release/result.json') if (base/'c-soak-release/result.json').exists() else {'status':'RUNNING','sustained_60_minutes':'PENDING'}
instance=read('c-soak-release/instance.json')
changed=[p for p,sha in instance['code_sha256'].items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=sha]
samples=read('c-soak-release/samples.json');browser=read('c-soak-release/browser.json');guard=read('production-guard.json');baselines=read('c-baselines-final.json')
working=[s['memory']['working_bytes'] for s in samples]
tasks={};sync_counts={}
for sample in samples:
    for card in sample['cards']:
        task=(card.get('analysis_status') or {}).get('current_task',{})
        if task.get('task_id'):tasks[task['task_id']]={'symbol':card['symbol'],'source':task.get('source'),'state':task.get('state')}
        state=card['sync']['status'];sync_counts[state]=sync_counts.get(state,0)+1
summary={'stage_a':'ISOLATED_PASS','stage_b':'ISOLATED_PASS','stage_c_isolated':'PASS' if soak.get('status')=='PASS' and soak.get('sustained_60_minutes')=='PASS' and not changed and guard['status']=='PASS' and baselines['status']=='READY' and log.strip().endswith('OK') else ('FAIL' if soak.get('status')=='FAIL' else 'PENDING'),
 'production_loaded':False,'production_auto':'WAITING_CONSOLIDATED_APPROVAL','production_provider_http_attempts':0,'production_old_workspace_deleted':False,
 'tests':{'count':int(match[1]),'seconds':float(match[2]),'status':'PASS' if log.strip().endswith('OK') else 'FAIL'},
 'browser_e2e':read('c-browser/result.json'),'soak':soak,'changed_since_soak_start':changed,
 'soak_growth':{'first':{k:samples[0][k] for k in ('elapsed_seconds','fact_count','event_count','fake_calls','opinion_count')},'last':{k:samples[-1][k] for k in ('elapsed_seconds','fact_count','event_count','fake_calls','opinion_count')},
 'navigations':browser['navigations'],'settings_peak_inflight':browser['peak_inflight'].get('/api/live/advisory/settings'),'pageerror':len(browser['pageerror']),'console_error':len(browser['console_error']),
 'memory_working_mb':{'first':round(working[0]/1024**2,2),'last':round(working[-1]/1024**2,2),'min':round(min(working)/1024**2,2),'max':round(max(working)/1024**2,2)},
 'memory_scope':'Combined isolated Agent/Web/Fake Provider/test samples process, not production Web alone',
 'task_count':len(tasks),'task_sources':sorted(set(t['source'] for t in tasks.values())),
 'task_count_by_symbol':{symbol:sum(t['symbol']==symbol for t in tasks.values()) for symbol in sorted(set(t['symbol'] for t in tasks.values()))},
 'sync_sample_counts':sync_counts,'external_console_error':len(browser.get('external_console_error',[]))},
 'performance':{k:{x:r.get(x) for x in ('count','errors','p50','p95')} for k,r in browser['routes'].items() if k.startswith('direct ')},
 'protection':{k:guard[k] for k in ('status','legacy_count','files_changes','database_files_checked','database_changes')},'baselines':{'status':baselines['status'],'frozen_baselines':baselines['frozen_baselines']}}
(base/'acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:summary[k] for k in ('stage_c_isolated','production_auto','tests','changed_since_soak_start','soak_growth')}))
