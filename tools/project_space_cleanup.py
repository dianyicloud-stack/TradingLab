"""Explicit project-only cleanup. No backups, archive moves, or reparse traversal."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone
import os,json,sys,stat
import sqlite3,hashlib
from contextlib import closing
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'docs/project_space_cleanup_result.json'
def scan():
    files=[];errors=[];stack=[ROOT]
    while stack:
        p=stack.pop()
        try:
            with os.scandir(p) as it:entries=list(it)
        except OSError as e:errors.append({'path':str(p),'error':type(e).__name__});continue
        for x in entries:
            try:
                s=x.stat(follow_symlinks=False)
                if x.is_symlink() or getattr(s,'st_file_attributes',0)&1024:errors.append({'path':x.path,'error':'REPARSE_NOT_FOLLOWED'});continue
                if x.is_dir(follow_symlinks=False):stack.append(Path(x.path))
                else:files.append((str(Path(x.path).relative_to(ROOT)),s.st_size))
            except OSError as e:errors.append({'path':x.path,'error':type(e).__name__})
    return files,errors
def summary(files,errors):
    groups=defaultdict(lambda:{'bytes':0,'files':0})
    for name,size in files:
        parts=Path(name).parts;key='/'.join(parts[:2])
        groups[key]['bytes']+=size;groups[key]['files']+=1
    return {'at':datetime.now(timezone.utc).isoformat(),'bytes':sum(s for _,s in files),'files':len(files),'errors':errors,
       'largest_dirs':sorted(groups.items(),key=lambda x:x[1]['bytes'],reverse=True)[:35],
       'largest_files':sorted(files,key=lambda x:x[1],reverse=True)[:25]}
def save(v):REPORT.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def safe(path):
    path=Path(path).absolute()
    if not path.is_relative_to(ROOT) or path==ROOT or path.resolve()!=path:raise ValueError('OUTSIDE_PROJECT_OR_REPARSE')
    for p in (path,*path.parents):
        if p==ROOT.parent:break
        st=p.stat(follow_symlinks=False)
        if p.is_symlink() or getattr(st,'st_file_attributes',0)&1024:raise ValueError('REPARSE_REJECTED')
    return path
def artifact_kind(name,size):
    p=Path(name);parts=p.parts
    if parts[0]=='artifacts':
        # Explicitly retained inputs used by current production-backlog tests.
        if len(parts)>1 and parts[1]=='input_budget_20260918':return None
        if p.name in ('web.final.stdout.log','web.final.stderr.log'):return None
        copies={'before','code-before','code','code-backup','baseline','production-copy'}
        if any(x in copies for x in parts[2:]):return '旧操作及验收回退副本'
        if p.suffix.lower() in ('.db','.sqlite','.sqlite3','.bak','.zip','.webm','.har') or p.name.endswith(('-wal','-shm')):return '测试数据库及浏览器trace录像'
        if p.suffix.lower() in ('.png','.jpg','.jpeg','.gif'):return '验收截图'
        if size>131072 and p.suffix.lower() in ('.json','.jsonl','.txt','.log','.ndjson'):return '大型接口转储及旧日志'
    if parts[0]=='tests' and len(parts)>2 and parts[1] not in ('fixtures','__pycache__'):
        # These exact generated roots were inspected and no active test process uses them.
        if parts[1].startswith(('tmp','agent-test-','lifecycle-soak-','lifecycle-test-','ui-stability-','m22-')) or parts[1] in ('tmp','.tmp'):return '已结束测试临时目录'
    if '__pycache__' in parts and parts[0] not in ('.venv','legacy'):return '可重建Python缓存'
    return None
def remove_files(candidates):
    value=json.loads(REPORT.read_text(encoding='utf-8'));parents=set()
    for name,category in candidates:
        p=ROOT/name
        try:
            safe(p);size=p.stat().st_size;p.unlink()
            value['deleted_bytes']+=size;value['deleted_files']+=1
            c=value['deleted_categories'].setdefault(category,{'bytes':0,'files':0});c['bytes']+=size;c['files']+=1
            parents.update(x for x in p.parents if x!=ROOT and x.is_relative_to(ROOT))
        except (OSError,ValueError) as e:value['deletion_errors'].append({'path':str(p),'error':type(e).__name__})
    # Remove only now-empty generated directories, never a source or owner root.
    for p in sorted(parents,key=lambda p:len(p.parts),reverse=True):
        rel=p.relative_to(ROOT)
        if rel.parts[0] not in ('artifacts','tests') or len(rel.parts)<2:continue
        try:safe(p);p.rmdir()
        except OSError:pass
    save(value);print(json.dumps({'deleted_bytes':value['deleted_bytes'],'deleted_files':value['deleted_files'],'categories':value['deleted_categories'],'failures':len(value['deletion_errors'])},ensure_ascii=False))
def ro(p):return sqlite3.connect(Path(p).as_uri()+'?mode=ro',uri=True)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=lambda b:{'hex':b.hex()}).encode()).hexdigest()
def guard():
    result={};p=ROOT/'data/runtime/live/advisory/advisory_runtime.db'
    with closing(ro(p)) as db:
        busy=db.execute("SELECT count(*) FROM live_analysis_requests WHERE status IN ('RUNNING','QUEUED')").fetchone()[0]
        busy+=db.execute("SELECT count(*) FROM advisory_coordinator WHERE state='RUNNING' OR pending>0").fetchone()[0]
        result['busy']=busy;result['runtime']={}
        for t in ('advisory_cursors','advisory_settings','live_preferences','live_retired_sessions','live_expired_sessions','tracking_deletion_intents'):
            result['runtime'][t]=digest(sorted(db.execute('SELECT * FROM '+t).fetchall()))
        result['task_statuses']=db.execute('SELECT request_id,status FROM live_analysis_requests ORDER BY request_id').fetchall()
    result['accounts']={}
    for p in (ROOT/'data/account/unified').glob('AC-*/account.db'):
        with closing(ro(p)) as db:
            result['accounts'][p.parent.name]={t:digest(db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall()) for t in ('ledger','projection')}
    for rel in ('data/system/market-source.json','.env'):
        result[rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    return result
def preflight():
    g=guard();v=json.loads(REPORT.read_text(encoding='utf-8'));v['protected_before']=g;save(v)
    print(json.dumps({'busy':g['busy'],'accounts':len(g['accounts'])}))
    if g['busy']:raise RuntimeError('ACTIVE_TASKS_WAIT_REQUIRED')
def diagnose_copies():
    with closing(ro(ROOT/'data/runtime/live/advisory/advisory_runtime.db')) as db:
        retired={r[0] for r in db.execute('SELECT session_id FROM live_retired_sessions')};status=dict(db.execute('SELECT symbol,status FROM tracking_deletion_intents'))
    base=ROOT/'data/runtime/live/advisory/tracking-deletions'
    result=[]
    for p in base.glob('*/manifest.json'):
        v=json.loads(p.read_text(encoding='utf-8'));result.append({'directory':str(p.parent),'symbol':v.get('symbol'),'status':status.get(v.get('symbol')),'sessions':v.get('sessions'),'missing_retired_boundary':list(set(v.get('sessions',[]))-retired)})
    print(json.dumps(result,ensure_ascii=False))
def offline():
    from adapters.runtime_lease import runtime_lease
    from adapters.web_instance import existing
    from app.shell.bootstrap import build_application
    from shared.config import Settings
    if existing(ROOT/'data','USER'):raise RuntimeError('STOP_WEB_FIRST')
    with runtime_lease(ROOT/'data'):
        if guard()['busy']:raise RuntimeError('ACTIVE_TASKS')
        a=build_application(Settings(ROOT,8765,ROOT/'data','USER',None));m=next(r.service for r in a.routers if type(r).__name__=='MaintenanceRouter')
        try:
            assert a.live_loop.status=='STOPPED' and not a.live_loop.thread
            m.configure_local_snapshots(False)
            bases=[ROOT/'data/runtime/live/advisory/maintenance-backups',ROOT/'data/live/advisory/maintenance-backups']
            candidates=[]
            for base in bases:
                if not base.exists():continue
                for folder in base.iterdir():
                    safe(folder)
                    if not folder.is_dir():continue
                    manifest=folder/'manifest.json'
                    if not manifest.exists():continue
                    val=json.loads(manifest.read_text(encoding='utf-8'));names=set(val['files'])|{'manifest.json'}
                    if {p.name for p in folder.iterdir()}!=names:continue
                    if not names<={'manifest.json','advisory_runtime.db','advisory.db','provider_requests.db'}:continue
                    candidates.extend((str((folder/name).relative_to(ROOT)),'项目内维护快照') for name in names)
            with m.live.runtime.connect(True) as db:
                retired={r[0] for r in db.execute('SELECT session_id FROM live_retired_sessions')}
                completed={r[0] for r in db.execute("SELECT symbol FROM tracking_deletion_intents WHERE status='DELETED'")}
            base=ROOT/'data/runtime/live/advisory/tracking-deletions'
            for folder in base.iterdir() if base.exists() else []:
                safe(folder);manifest=folder/'manifest.json'
                if not manifest.exists():continue
                val=json.loads(manifest.read_text(encoding='utf-8'))
                if val.get('symbol') not in completed or not set(val.get('sessions',[])).issubset(retired):continue
                if {p.name for p in folder.iterdir()}!={'manifest.json','advisory_runtime.db'}:continue
                candidates.extend((str((folder/name).relative_to(ROOT)),'已完成股票删除的旧数据库副本') for name in ('manifest.json','advisory_runtime.db'))
            remove_files(candidates)
            # Only approved owner snapshots/deletion copies; remove their empty shells.
            for base in [*bases,ROOT/'data/runtime/live/advisory/tracking-deletions']:
                for folder in list(base.iterdir()) if base.exists() else []:
                    try:safe(folder);folder.rmdir()
                    except OSError:pass
                try:safe(base);base.rmdir()
                except OSError:pass
            results=m.live.compact_offline()
            v=json.loads(REPORT.read_text(encoding='utf-8'));v['compaction']=results;v['protected_after_offline']=guard();v['local_snapshots_enabled']=False;save(v)
            assert digest(v['protected_before'])==digest(v['protected_after_offline']),'PROTECTED_DATA_CHANGED'
            print(json.dumps({'compaction':results,'protected_data_unchanged':True,'new_backup':False},ensure_ascii=False))
        finally:a.live_loop.advisory._auto_pool.shutdown(wait=True)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    sys.path.insert(0,str(ROOT))
    if sys.argv[1]=='preflight':preflight();raise SystemExit(0)
    if sys.argv[1]=='offline':offline();raise SystemExit(0)
    if sys.argv[1]=='diagnose-copies':diagnose_copies();raise SystemExit(0)
    files,errors=scan();value=summary(files,errors)
    if sys.argv[1]=='before':save({'before':value,'deleted_categories':{},'deleted_bytes':0,'deleted_files':0,'deletion_errors':[]})
    if sys.argv[1]=='delete-generated':remove_files([(n,k) for n,s in files if (k:=artifact_kind(n,s))])
    else:print(json.dumps(value,ensure_ascii=False))
