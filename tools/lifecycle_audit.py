"""Read-only inventory: no owner initialization, no link traversal, no credentials."""
from pathlib import Path
from datetime import datetime,timezone
import os,stat,sqlite3,json,collections,urllib.request,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/lifecycle_20260921'

def readonly(path):
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    db.execute('PRAGMA query_only=ON');return db

def category(relative,agent=False):
    p=relative.replace('\\','/').lower()
    if 'backup' in p or 'tracking-deletions/' in p or '/source-history/' in p:return 'backups'
    if agent:return 'market_facts' if p.endswith(('.db','.db-wal','.db-shm','.jsonl')) or p.startswith('native/') else 'agent_runtime'
    if p.startswith(('.venv/','node_modules/')):return 'dependencies'
    if p.startswith('artifacts/') or p.startswith('tests/') and ('/data/' in p or '/workspace/' in p):return 'test_artifacts'
    if p.startswith('data/account/'):return 'account'
    if p.startswith('data/decisions/'):return 'ai_and_decisions'
    if p.startswith(('data/runtime/','data/system/')):return 'runtime_configuration'
    if p.startswith('data/learning/'):return 'manual_learning'
    if p.startswith('data/market/'):return 'market_store'
    if '/logs/' in p or p.endswith(('.log','.log.1')):return 'logs'
    if p.startswith('data/'):return 'other_data_protected'
    if p.startswith(('exports/','manual/')):return 'manual_files'
    return 'code_and_other_files'

def scan(root,agent=False):
    files=[];skipped=[];stack=[root];directories=0
    while stack:
        directory=stack.pop();directories+=1
        try:entries=list(os.scandir(directory))
        except OSError as e:skipped.append({'path':str(directory),'reason':type(e).__name__});continue
        for entry in entries:
            try:
                st=entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(st,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
                    skipped.append({'path':entry.path,'reason':'REPARSE_POINT_NOT_FOLLOWED'});continue
                if entry.is_dir(follow_symlinks=False):stack.append(Path(entry.path));continue
                p=Path(entry.path);relative=str(p.relative_to(root));files.append({'path':str(p),'relative':relative,'bytes':st.st_size,'modified_at':datetime.fromtimestamp(st.st_mtime,timezone.utc).isoformat(),'category':category(relative,agent)})
            except OSError as e:skipped.append({'path':entry.path,'reason':type(e).__name__})
    totals={};dirs=collections.Counter()
    for f in files:
        item=totals.setdefault(f['category'],{'bytes':0,'files':0});item['bytes']+=f['bytes'];item['files']+=1
        parent=Path(f['path']).parent
        while parent!=root and parent.is_relative_to(root):dirs[str(parent)]+=f['bytes'];parent=parent.parent
    return {'root':str(root),'bytes':sum(x['bytes'] for x in files),'files':len(files),'directories':directories,'categories':totals,
            'top20_files':sorted(files,key=lambda x:x['bytes'],reverse=True)[:20],
            'top20_directories':[{'path':p,'bytes':n} for p,n in dirs.most_common(20)],'skipped':skipped,'inventory':files}

def database(path):
    value={'path':str(path),'main_bytes':path.stat().st_size,'wal_bytes':Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0,'shm_bytes':Path(str(path)+'-shm').stat().st_size if Path(str(path)+'-shm').exists() else 0}
    try:
        with readonly(path) as db:
            for key in ('page_count','page_size','freelist_count','journal_mode'):value[key]=db.execute('PRAGMA '+key).fetchone()[0]
            value['reusable_page_bytes']=value['freelist_count']*value['page_size'];tables={}
            for (name,) in db.execute("select name from sqlite_master where type='table'"):
                q='"'+name.replace('"','""')+'"';tables[name]={'rows':db.execute('select count(*) from '+q).fetchone()[0]}
            try:
                for name,pages,payload,unused in db.execute('select name,sum(pgsize),sum(payload),sum(unused) from dbstat group by name'):
                    tables.setdefault(name,{}) .update(btree_bytes=pages,payload_bytes=payload,in_page_unused_bytes=unused)
            except sqlite3.Error:pass
            value['tables']=tables
    except sqlite3.Error as e:value['error']=type(e).__name__
    return value

def accounts(data):
    result=[]
    for path in (data/'account/unified').glob('AC-*/account.db'):
        with readonly(path) as db:
            first=db.execute('select payload from ledger order by seq limit 1').fetchone()
            if not first:continue
            first=json.loads(first[0]);meta=first.get('account',{})
            if meta.get('namespace')!='USER' or meta.get('account_type')!='LIVE_SHADOW':continue
            row=db.execute('select body from projection where id=1').fetchone();projection=json.loads(row[0]) if row else {}
            policy=projection.get('policy',first.get('policy',{}));events=[]
            for kind,payload in db.execute('select event_type,payload from ledger order by seq desc limit 20'):
                v=json.loads(payload);events.append({'kind':kind,**{k:v[k] for k in ('created_at','advisory_id','intent_id','reason','status','symbol','portfolio_action') if k in v},'keys':list(v)})
            result.append({'account_id':meta.get('account_id'),'generation':meta.get('account_generation'),'status':meta.get('status'),
                           'execution_mode':policy.get('ai_execution_mode'),'projection_keys':list(projection),'recent_events':events,
                           'event_counts':dict(db.execute('select event_type,count(*) from ledger group by event_type'))})
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True);data=ROOT/os.environ.get('TRADING_LAB_DATA_ROOT','data')
    configuration=json.loads((data/'system/market-source.json').read_text(encoding='utf-8'))['config']
    agent=Path(os.environ.get('TRADING_LAB_MARKET_AGENT_ROOT') or configuration['market_agent_root']).resolve()
    runtime={}
    for route in ('/healthz','/api/live/runtime-version','/api/live/mode'):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765'+route,timeout=3) as response:v=json.load(response)
            runtime[route]={k:v[k] for k in ('status','instance_id','build_id','source_root','source_owner','source_generation','listener_state') if k in v}
        except Exception as e:runtime[route]={'error':type(e).__name__}
    if runtime.get('/api/live/runtime-version',{}).get('source_root'):agent=Path(runtime['/api/live/runtime-version']['source_root']).resolve()
    roots=[scan(ROOT),scan(agent,True)];dbs=[]
    for inv in roots:
        for row in inv['inventory']:
            p=Path(row['path'])
            if p.suffix=='.db' and (p.is_relative_to(data) or p.is_relative_to(agent)):dbs.append(database(p))
    report={'measured_at':datetime.now(timezone.utc).isoformat(),'project_root':str(ROOT),'data_root':str(data.resolve()),'agent_root':str(agent),
            'source':configuration['active_market_source'],'runtime':runtime,'roots':roots,'databases':dbs,'accounts':accounts(data),
            'growth_note':'One inventory is a measured size, not proof of net growth. Compare later measurement; modified_at is write activity only.'}
    with readonly(data/'decisions/advisory/advisory.db') as db:
        report['opinion_days']=[dict(date=d,count=n,payload_bytes=b) for d,n,b in db.execute("select substr(generated_at,1,10),count(*),sum(length(cast(payload as blob))) from advisory_opinions group by 1")]
        report['latest_plans']=[]
        for (raw,) in db.execute('select payload from advisory_opinions order by generated_at desc limit 12'):
            v=json.loads(raw);report['latest_plans'].append({k:v.get(k) for k in ('advisory_id','symbol','generated_at','action','portfolio_plan')})
    with readonly(data/'runtime/live/advisory/advisory_runtime.db') as db:
        names=[r[0] for r in db.execute("select name from sqlite_master where type='table'")]
        report['live_runtime_tables']=names
        if 'portfolio_outcomes' in names:
            report['portfolio_outcomes']=[json.loads(r[0]) for r in db.execute('select payload from portfolio_outcomes order by rowid desc limit 12')]
    target=OUT/('space-'+str(time.time_ns())+'.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(target),'measured_at':report['measured_at'],'roots':[{k:r[k] for k in ('root','bytes','files','directories','categories')} for r in roots],
                      'accounts':[{'account_id':a['account_id'],'mode':a['execution_mode'],'counts':a['event_counts']} for a in report['accounts']]},ensure_ascii=False))

if __name__=='__main__':main()
