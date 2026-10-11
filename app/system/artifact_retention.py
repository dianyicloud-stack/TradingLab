"""System-owned generated outputs only. Unknown/manual files are never inferred."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,os,stat
from shared.storage.maintenance import checked,sha

class ArtifactRetention:
    def __init__(self,root):self.root=Path(root);self.registry=self.root/'maintenance-registry.json'
    def records(self):return json.loads(self.registry.read_text(encoding='utf-8')) if self.registry.exists() else []
    def register(self,run_id,kind,files,*,pinned=False,finished_at=None):
        if kind not in ('TEST_ARTIFACT','ROLLBACK','LOG','TEMP'):raise ValueError('UNKNOWN_ARTIFACT_CLASS')
        rows=self.records()
        if any(r['run_id']==run_id for r in rows):return
        items=[]
        for relative in files:
            p=checked(self.root,self.root/relative)
            if not p.is_file():raise ValueError('ARTIFACT_FILE_REQUIRED')
            items.append({'path':str(p.relative_to(self.root)),'bytes':p.stat().st_size,'sha256':sha(p)})
        rows.append({'run_id':run_id,'kind':kind,'files':items,'pinned':pinned,'finished_at':finished_at or datetime.now(timezone.utc).isoformat(),'status':'COMPLETE'})
        self.root.mkdir(parents=True,exist_ok=True);tmp=self.registry.with_suffix('.tmp');tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.registry)
    def preview(self,now=None):
        now=now or datetime.now(timezone.utc);rows=self.records();candidate=[];kept=[]
        limits={'TEST_ARTIFACT':(7,256*1024*1024,2),'ROLLBACK':(14,256*1024*1024,2),'LOG':(7,10*1024*1024,1),'TEMP':(2,64*1024*1024,1)}
        for kind,(days,cap,count) in limits.items():
            group=sorted((r for r in rows if r['kind']==kind and r['status']=='COMPLETE'),key=lambda r:r['finished_at'],reverse=True);used=0
            for i,r in enumerate(group):
                size=sum(f['bytes'] for f in r['files']);used+=size;age=now-datetime.fromisoformat(r['finished_at'])
                reason='MANUAL_PIN' if r.get('pinned') else 'CURRENT_ROLLBACK_OR_RECENT_RUN' if i<count else None
                if not reason and (age>timedelta(days=days) or used>cap):candidate.append(r)
                else:kept.append({'run_id':r['run_id'],'reason':reason or 'WITHIN_LIMIT'})
        return {'candidates':candidate,'kept':kept,'records':sum(len(r['files']) for r in candidate),'bytes':sum(f['bytes'] for r in candidate for f in r['files']),'unknown':'UNREGISTERED_FILES_PRESERVED'}
    def step(self,limit=30):
        rows=self.records();plan=self.preview();deleted=0;released=0
        for item in plan['candidates']:
            target=next(r for r in rows if r['run_id']==item['run_id']);done=set(target.get('removed',[]))
            for f in target['files']:
                if f['path'] in done:continue
                p=checked(self.root,self.root/f['path'])
                if p.exists():
                    if not p.is_file() or sha(p)!=f['sha256']:continue # Changed/manually edited output stays.
                    released+=p.stat().st_size;p.unlink()
                done.add(f['path']);deleted+=1
                if deleted>=limit:break
            target['removed']=sorted(done)
            if len(done)==len(target['files']):target.update(status='EXPIRED',files=[],removed=[])
            if deleted>=limit:break
        if deleted:
            tmp=self.registry.with_suffix('.tmp');tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.registry)
        return {'status':'MORE' if deleted else 'DONE','files_deleted':deleted,'disk_released_bytes':released}

def scan_capacity(root,agent=False,*,safety_project=None,owner_roots=()):
    """Read-only metadata scan without following junctions; no file contents."""
    categories={};errors=[];error_count=0;overflow={'checked':0,'blocking':0};at=datetime.now(timezone.utc).isoformat();root=Path(root).absolute();stack=[root]
    def problem(path,error):
        nonlocal error_count
        error_count+=1
        detail={'path':str(path),'error':type(error).__name__ if isinstance(error,Exception) else error,'measured_at':at,
            'category':'市场事实/Agent保护依赖' if agent else '测试目录' if Path(path).is_relative_to(root/'tests') else '尚未确定',
            'winerror':getattr(error,'winerror',None)}
        if len(errors)<32:errors.append(detail)
        elif safety_project is not None:
            # Classify EVERY omitted path; the log bound is not a safety bound.
            verdict=scan_safety({'errors':[detail],'errors_truncated':False},safety_project,owner_roots)[0]
            overflow['checked']+=1;overflow['blocking']+=int(verdict['blocks_cleanup'])
    try:checked(root,root)
    except (OSError,ValueError) as e:problem(root,e);stack=[]
    while stack:
        current=stack.pop()
        try:
            with os.scandir(current) as iterator:entries=list(iterator)
        except OSError as e:problem(current,e);continue
        for entry in entries:
            try:st=entry.stat(follow_symlinks=False)
            except OSError as e:problem(entry.path,e);continue
            if entry.is_symlink() or getattr(st,'st_file_attributes',0)&1024:problem(entry.path,'REPARSE_POINT_NOT_FOLLOWED');continue
            if entry.is_dir(follow_symlinks=False):stack.append(Path(entry.path));continue
            relative=Path(entry.path).relative_to(root).as_posix()
            category='账户' if relative.startswith('data/account/') else '备份' if ('backup' in relative or 'tracking-deletions/' in relative) else '测试产物' if relative.startswith(('artifacts/','tests/tmp/')) else '依赖' if relative.startswith(('.venv/','node_modules/')) else 'AI输入与意见' if relative.startswith('data/live/') else '运行状态' if relative.startswith('data/runtime/') else '日志' if relative.endswith('.log') else '代码及其他保护内容'
            if agent:category='备份（Agent）' if ('backup' in relative or 'tracking-deletions/' in relative) else '市场事实（Agent）' if relative.startswith('market_agent.db') else '日志（Agent）' if relative.endswith('.log') else 'Agent运行状态'
            c=categories.setdefault(category,{'label':category,'bytes':0,'files':0});c['bytes']+=st.st_size;c['files']+=1
    return {'status':'PARTIAL' if errors and categories else 'FAILED' if errors else 'COMPLETE','measured_at':at,'categories':categories,
            'known_bytes':sum(v['bytes'] for v in categories.values()),'total_is_lower_bound':bool(error_count),'errors':errors,'error_count':error_count,'errors_truncated':error_count>len(errors),
            'overflow_safety':{**overflow,'project':str(Path(safety_project).absolute()) if safety_project is not None else None,'owner_roots':sorted(str(Path(p).resolve()) for p in owner_roots)}}

def measure(root,agent=False):
    """Compatibility display helper; maintenance uses the full scan result."""
    return scan_capacity(root,agent)['categories']

def scan_safety(scan,project,owner_roots):
    """Only contract-excluded test paths with proven non-overlap may be display-only."""
    result=[];project=Path(project).absolute()
    for e in scan['errors']:
        p=Path(e['path']).absolute();independent=False
        try:
            checked(project,p)
            independent=p.is_relative_to(project/'tests') and e['error']!='REPARSE_POINT_NOT_FOLLOWED' and all(
                not (p.is_relative_to(Path(r).resolve()) or Path(r).resolve().is_relative_to(p)) for r in owner_roots)
        except (OSError,ValueError):pass
        result.append({**e,'blocks_cleanup':not independent,'scope':'DISPLAY_ONLY_EXCLUDED_TEST_TREE' if independent else 'OWNER_OR_UNKNOWN_DEPENDENCY',
                       'proof':'Outside registered artifact root and every owner capability; no ancestor reparse' if independent else 'Candidate/protection overlap or identity not established'})
    if scan['errors_truncated']:
        v=scan.get('overflow_safety',{});count=scan.get('error_count',0)-len(scan['errors'])
        proven=(count>0 and v.get('checked')==count and v.get('blocking')==0 and v.get('project')==str(project)
                and v.get('owner_roots')==sorted(str(Path(p).resolve()) for p in owner_roots))
        result.append({'error':'ERROR_DETAILS_LIMIT','blocks_cleanup':not proven,'scope':'DISPLAY_ONLY_EXCLUDED_TEST_TREE' if proven else 'UNKNOWN_DEPENDENCY',
                       'omitted_errors':max(0,count),'checked_errors':v.get('checked',0),'blocking_errors':v.get('blocking'),'proof':'Every omitted path checked against the same owner roots' if proven else 'Omitted paths unsafe or not fully checked'})
    return result
