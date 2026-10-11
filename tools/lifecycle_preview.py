"""Read-only production candidate inventory. Not an execution authorization."""
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
import sys,json,sqlite3,collections,os
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.lifecycle_audit import readonly,scan
from bridges.market_agent import AgentClient

def main():
    out=ROOT/'artifacts/lifecycle_20260921';data=ROOT/'data';config=json.loads((data/'system/market-source.json').read_text(encoding='utf-8'))['config'];root=Path(config['market_agent_root'])
    descriptor=json.loads((root/'connection.json').read_text(encoding='utf-8'))
    report={'measured_at':datetime.now(timezone.utc).isoformat(),'mode':'READ_ONLY_PROVISIONAL','source':config['active_market_source'],'agent_root':str(root),'agent_pid':descriptor.get('pid'),
            'production_loaded':False,'policy_enabled':False,'executed':False,'required':'New Agent readiness certificate + owner preview + user implementation approval before deletion.'}
    try:
        v=AgentClient(root).query();report['agent']={k:v.get(k) for k in ('source','status','agent_state','trading_date','last_cycle_at','capabilities')}
        report['agent']['sessions']=[{k:s.get(k) for k in ('symbol','date','tracking_session_id','lifecycle_status')} for s in v['sessions']]
        day=max(s['date'] for s in v['sessions']);report['keep_day']=day
    except Exception as e:report['agent_error']=type(e).__name__;day='2026-09-21';report['keep_day_assumption']=day
    protected=set();account_reports=[]
    def refs(v):
        if isinstance(v,dict):
            if isinstance(v.get('advisory_id'),str):protected.add(v['advisory_id'])
            for x in v.values():refs(x)
        elif isinstance(v,list):
            for x in v:refs(x)
    for p in (data/'account/unified').glob('AC-*/account.db'):
        with closing(readonly(p)) as db:
            rows=[json.loads(r[0]) for r in db.execute('select payload from ledger order by seq')];meta=rows[0]['account']
            if meta.get('namespace')!='USER':continue
            refs(rows);projection=json.loads(db.execute('select body from projection where id=1').fetchone()[0])
            account_reports.append({'type':meta['account_type'],'execution_mode':projection['policy']['ai_execution_mode'],'ledger_counts':dict(collections.Counter(r['event_type'] for r in rows))})
    with closing(readonly(data/'learning/learning.db')) as db:
        if db.execute("select 1 from sqlite_master where name='saved_advisory_cases'").fetchone():protected.update(r[0] for r in db.execute('select source_advisory_id from saved_advisory_cases'))
    report['accounts']=account_reports;report['protected_opinion_count']=len(protected)
    opinions=[];plans=[]
    with closing(readonly(data/'decisions/advisory/advisory.db')) as db:
        for oid,iid,symbol,date,raw,body in db.execute('select o.advisory_id,o.input_id,o.symbol,o.session_date,o.payload,i.payload from advisory_opinions o join advisory_inputs i using(input_id)'):
            if date<day:opinions.append({'advisory_id':oid,'input_id':iid,'date':date,'bytes':len(raw.encode())+len(body.encode()),'protected':oid in protected})
            v=json.loads(raw)
            if date==day and v.get('portfolio_plan',{}).get('portfolio_action')=='OPEN':plans.append({k:v.get(k) for k in ('advisory_id','symbol','generated_at','portfolio_plan')})
    report['old_opinions']=opinions;report['open_plans']=plans
    tasks=[]
    with closing(readonly(data/'runtime/live/advisory/advisory_runtime.db')) as db:
        report['task_status_counts']=dict(db.execute('select status,count(*) from live_analysis_requests group by status'))
        for rid,status,raw in db.execute('select request_id,status,payload from live_analysis_requests'):
            v=json.loads(raw);date=v.get('frozen',{}).get('session_date') or str(v.get('task',{}).get('created_at',''))[:10]
            if date and date<day:tasks.append({'request_id':rid,'date':date,'status':status,'bytes':len(raw.encode())})
        for p in plans:
            row=db.execute('select payload from portfolio_outcomes where advisory_id=?',(p['advisory_id'],)).fetchone();p['actual_outcome']=json.loads(row[0]) if row else None
    report['old_tasks']=tasks
    with closing(readonly(root/'market_agent.db')) as db:
        report['market_counts_by_kind_and_day']=[{'kind':k,'date':d,'rows':n,'payload_bytes':b} for k,d,n,b in db.execute("select kind,coalesce(json_extract(payload,'$.session_date'),json_extract(payload,'$.date'),substr(recorded_at,1,10)),count(*),sum(length(cast(payload as blob))) from facts group by 1,2")]
        report['agent_accounting']={key:db.execute('pragma '+key).fetchone()[0] for key in ('page_size','page_count','freelist_count')}
    report['provisional_old_ai_bytes']=sum(r['bytes'] for r in opinions if not r['protected'])+sum(r['bytes'] for r in tasks)
    report['retired_workspace']=scan(root.parent/'V2AWorkspace')
    report['configuration_path']=str(data/'system/market-source.json');report['external_shared_runtime']={'python':sys.base_prefix,'ownership':'SHARED_TOOL_RUNTIME_NOT_CLEANABLE'}
    (out/'production-preview.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('measured_at','agent_pid','accounts','provisional_old_ai_bytes','protected_opinion_count')},ensure_ascii=False))
if __name__=='__main__':main()
