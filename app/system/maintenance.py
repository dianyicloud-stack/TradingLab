"""System orchestration through owner contracts; GET returns cached measurements."""
from pathlib import Path
from threading import Thread,Event,Lock
from datetime import datetime,timezone
from dataclasses import asdict
import json,os,time
from contracts.maintenance import POLICY,RetentionBoundary
from engines.live.retention import LiveRetention

class MaintenanceService:
    def __init__(self,store,advisory,agent,portfolio,manual_refs,calendar,inventory_root=None,artifact_root=None,protected_roots=()):
        self.store=store;self.live=LiveRetention(advisory);self.agent=agent;self.portfolio=portfolio;self.manual_refs=manual_refs;self.calendar=calendar
        self.stop=Event();self.wake=Event();self.lock=Lock();self.thread=None;self.command=None
        self.path=store.path('maintenance.json');self.policy_path=store.path('retention-policy.json')
        self.state=self._read(self.path,{'status':'NOT_MEASURED','measured_at':None,'policy':POLICY,'pending':None})
        self.policy={**POLICY,**self._read(self.policy_path,{})};self.state['policy']=self.policy
        self.inventory_root=inventory_root
        self.protected_roots=tuple(protected_roots)
        self.working_caches=()
        from .artifact_retention import ArtifactRetention
        self.artifacts=ArtifactRetention(artifact_root) if artifact_root else None

    @staticmethod
    def _read(path,default):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.state,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
    def read(self):return json.loads(json.dumps({**self.state,'policy':self.policy}))
    def configure_local_snapshots(self,enabled):
        """Explicit offline System-owner operation; account evidence is unaffected."""
        if type(enabled) is not bool:raise ValueError('INVALID_BACKUP_SETTING')
        with self.lock:
            self.policy={**self.policy,'local_snapshots_enabled':enabled}
            self.policy_path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.policy_path.with_suffix('.tmp');temp.write_text(json.dumps(self.policy),encoding='utf-8');temp.replace(self.policy_path)
            self.state['policy']=self.policy;self._save()
    def request(self,action,payload=None):
        if action=='enable':
            if (payload or {}).get('confirmation')!='ENABLE_LATEST_READY_DAY_RETENTION':return {'status':'CONFIRMATION_REQUIRED'}
            self.policy={**POLICY,**self.policy,'enabled':True};self.policy_path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.policy_path.with_suffix('.tmp');temp.write_text(json.dumps(self.policy),encoding='utf-8');temp.replace(self.policy_path)
        if action=='apply' and not self.policy['enabled']:return {'status':'POLICY_DISABLED','message':'策略尚未启用；请先完成预览与正式实施确认。'}
        if action not in ('preview','apply','enable'):return {'status':'INVALID_COMMAND'}
        self.command='preview' if action=='preview' else 'apply';self.wake.set();return {'status':'QUEUED'}
    def preview(self):
        blockers=[];checks={'snapshots':'NOT_CREATED','live_candidates':'NOT_CHECKED'};source={};agent={};refs=set()
        def failed(code,scope):blockers.append({'code':code,'scope':scope})
        try:
            source=self.agent.query()
            if not {'DAILY_RETENTION_V1','RETENTION_VALIDATION_V2'}.issubset(source.get('capabilities',[])):failed('AGENT_UPGRADE_REQUIRED','AGENT')
            else:
                agent=self.agent.command({'schema_version':'1.0','source':source['source'],'action':'RETENTION_PREVIEW'})
                if agent.get('blocked'):failed(agent.get('reason','AGENT_NOT_READY'),'AGENT_BASELINES')
        except Exception as e:failed(getattr(e,'code',type(e).__name__),'AGENT')
        checks['readiness']=agent.get('validation',{'status':'NOT_CHECKED'})
        try:
            storage=self.live.snapshot_requirements() if self.policy.get('local_snapshots_enabled',True) else {}
            if agent.get('storage'):storage['agent']=agent['storage']
            checks['snapshot_requirements']=storage
            for owner,s in storage.items():
                if s['status']!='PASSED':failed(s.get('reason','SNAPSHOT_NOT_READY'),'SNAPSHOT_'+owner.upper())
        except Exception as e:failed(getattr(e,'code',type(e).__name__),'SNAPSHOT_REQUIREMENTS');checks['snapshot_requirements']={'status':'NOT_CHECKED'}
        try:
            busy=self.live.busy();checks['tasks']='BUSY' if busy else 'PASSED'
            if busy:failed('ACTIVE_OR_QUEUED_TASK','LIVE')
        except Exception as e:failed(type(e).__name__,'LIVE_TASKS');checks['tasks']='NOT_CHECKED'
        try:
            refs=set(self.portfolio.retention_evidence());refs.update(r.get('source_advisory_id') or r.get('advisory_id') for r in self.manual_refs() if r.get('source_advisory_id') or r.get('advisory_id'))
            checks['references']={'status':'INSPECTED_NOT_SAVED','protected_opinions':len(refs)}
        except Exception as e:failed(getattr(e,'code',type(e).__name__),'ACCOUNT_OR_MANUAL_REFERENCES');checks['references']={'status':'NOT_CHECKED'}
        if not agent or agent.get('blocked') or 'keep_day' not in agent:
            return {'blocked':True,'reason':blockers[0]['code'] if blockers else 'AGENT_NOT_READY','blockers':blockers,'checks':checks,'owners':{'agent':agent}}
        day=agent['keep_day']
        if not self.policy.get('local_snapshots_enabled',True):checks['snapshots']='LOCAL_DISABLED'
        requirements=checks.get('snapshot_requirements',{})
        if all(isinstance(requirements.get(owner),dict) and 'retain-'+day in requirements[owner].get('verified_runs',[]) for owner in ('runtime','opinions','agent')):
            checks['snapshots']='VERIFIED'
        if not self.calendar.is_open(day):failed('CALENDAR_NOT_READY','TRADING_DAY')
        boundary=RetentionBoundary(day,tuple(sorted(refs)),tuple(agent.get('protected_sessions',[])),'retain-'+day)
        live=self.live.preview(boundary)
        checks['live_candidates']='INSPECTED'
        if live['blocked'] and not any(b['code']==live.get('reason') for b in blockers):failed(live.get('reason','LIVE_NOT_READY'),'LIVE')
        return {'blocked':bool(blockers),'reason':blockers[0]['code'] if blockers else None,'blockers':blockers,'checks':checks,'boundary':asdict(boundary),'source':source['source'],
                'owners':{'agent':agent,'live':live},'records':agent['records']+live['records'],
                'estimated_logical_bytes':agent['estimated_logical_bytes']+live['estimated_logical_bytes'],
                'retained':'账户账本和证据、手工保存、配置、身份、水位、原生比较基准；未知文件暂缓。'}

    def run_once(self,apply=False):
        if not self.lock.acquire(blocking=False):return {'status':'BUSY'}
        try:
            self.state.pop('reason',None);scope_errors=[]
            if self.inventory_root:
                from .artifact_retention import scan_capacity,scan_safety
                roots=[Path(self.inventory_root)/'data',self.live.runtime.store.path(),self.live.opinions.store.path(),*self.protected_roots]
                if self.artifacts:roots.append(self.artifacts.root)
                if isinstance(getattr(self.agent,'root',None),(str,Path)):
                    roots.append(Path(self.agent.root))
                scans=[scan_capacity(self.inventory_root,safety_project=self.inventory_root,owner_roots=roots)]
                if isinstance(getattr(self.agent,'root',None),(str,Path)):
                    scans.append(scan_capacity(self.agent.root,True,safety_project=self.inventory_root,owner_roots=roots))
                categories={}
                for scan in scans:
                    categories.update(scan['categories']);scope_errors.extend(scan_safety(scan,self.inventory_root,roots))
                self.state['capacity_scan']={'status':'COMPLETE' if all(s['status']=='COMPLETE' for s in scans) else 'PARTIAL' if categories else 'FAILED',
                    'errors':scope_errors,'measured_at':datetime.now(timezone.utc).isoformat(),'total_is_lower_bound':bool(scope_errors)}
                self.state['capacity']=categories;self.state['measured_at']=self.state['capacity_scan']['measured_at']
                if self.state['capacity_scan']['status']=='COMPLETE':self.state['last_complete_measurement']={'measured_at':self.state['measured_at'],'categories':categories}
            artifact_error=None
            if self.artifacts:
                try:self.state['artifact_preview']=self.artifacts.preview()
                except Exception as e:artifact_error={'code':type(e).__name__,'scope':'REGISTERED_ARTIFACTS'}
            pending=self.preview()
            blockers=list(pending.get('blockers',[]));blockers.extend({'code':e['error'],'scope':e['scope'],'path':e.get('path')} for e in scope_errors if e['blocks_cleanup'])
            if artifact_error:blockers.append(artifact_error)
            pending.update(blocked=pending.get('blocked',False) or bool(blockers),blockers=blockers)
            self.state.update(pending=pending,status='DEFERRED' if pending['blocked'] else 'PREVIEW',checks=pending.get('checks',{}),blockers=blockers);self._save()
            if not apply or not self.policy['enabled'] or pending.get('blocked'):return self.read()
            boundary=RetentionBoundary(**pending['boundary']);run=boundary.run_id
            self.state['working_cache_cleanup']=[owner.expire(boundary.keep_day) for owner in self.working_caches]
            self._save()
            prior=self.state.get('last_result',{})
            if prior.get('run_id')==run and prior.get('status')=='DONE':
                if self.artifacts and not self.live.busy():self.state['last_result']['artifact_cleanup']=self.artifacts.step();self._save()
                return self.read()
            # Preserve evidence BEFORE any source deletion. Readers never call this.
            with self.live.service._locks_guard,self.portfolio._execution_lock:
                if self.live.busy():self.state['status']='DEFERRED';self._save();return self.read()
                self.portfolio.retention_evidence(preserve=True)
                if self.policy.get('local_snapshots_enabled',True):self.live.snapshot(run)
                command={'schema_version':'1.0','source':pending['source'],'confirmation':'OWNER_RETENTION_V1','keep_day':boundary.keep_day,'run_id':run,'protected_sessions':list(boundary.protected_sessions)}
                self.agent.command({**command,'action':'RETENTION_BACKUP'})
                self.state['checks']['snapshots']='VERIFIED' if self.policy.get('local_snapshots_enabled',True) else 'LOCAL_DISABLED';self.state['checks']['references']['status']='SAVED_AND_VERIFIED';self._save()
            self.state['journal']={'run_id':run,'phase':'LIVE','started_at':datetime.now(timezone.utc).isoformat()};self._save()
            total=0
            while not self.stop.is_set():
                current=self.preview()
                if current.get('blocked') or current.get('boundary')!=asdict(boundary):
                    if not current.get('blocked'):current.update(blocked=True,blockers=[{'code':'MAINTENANCE_BOUNDARY_CHANGED','scope':'REFERENCES_OR_TRADING_DAY'}])
                    self.state.update(status='DEFERRED',pending=current,blockers=current.get('blockers',[]));self._save();return self.read()
                with self.live.service._locks_guard,self.portfolio._execution_lock:
                    # Re-evaluate human-created references between bounded batches.
                    refs=set(self.portfolio.retention_evidence());refs.update(r.get('source_advisory_id') or r.get('advisory_id') for r in self.manual_refs() if r.get('source_advisory_id') or r.get('advisory_id'))
                    b=RetentionBoundary(boundary.keep_day,tuple(refs),boundary.protected_sessions,run)
                    result=self.live.step(b)
                total+=result.get('logical_records_deleted_or_compacted',0)
                if result['status']=='DEFERRED':self.state['status']='DEFERRED';self._save();return self.read()
                if result['status']=='DONE':break
                self.stop.wait(.05)
            self.state['journal']['phase']='AGENT';self._save()
            while not self.stop.is_set():
                current=self.preview()
                if current.get('blocked') or current.get('boundary')!=asdict(boundary):
                    if not current.get('blocked'):current.update(blocked=True,blockers=[{'code':'MAINTENANCE_BOUNDARY_CHANGED','scope':'REFERENCES_OR_TRADING_DAY'}])
                    self.state.update(status='DEFERRED',pending=current,blockers=current.get('blockers',[]));self._save();return self.read()
                if self.live.busy():self.state['status']='DEFERRED';self._save();return self.read()
                result=self.agent.command({**command,'action':'RETENTION_APPLY'});total+=result.get('logical_records_deleted',0)
                if result['status']=='DONE':break
                self.stop.wait(.1)
            if self.stop.is_set():self.state['status']='INTERRUPTED'
            else:self.state.update(status='DONE',last_result={'run_id':run,'status':'DONE','records':total,'finished_at':datetime.now(timezone.utc).isoformat(),'disk_reclaimed_bytes':0,'note':'SQLite 空闲页可复用，未执行 VACUUM；磁盘释放需单独测量。'})
            if self.artifacts and not self.stop.is_set() and not self.live.busy():
                result=self.artifacts.step();self.state['last_result']['artifact_cleanup']=result
            self._save();return self.read()
        except Exception as e:
            code=getattr(e,'code',type(e).__name__)
            self.state.update(status='DEFERRED',reason=code,blockers=[*self.state.get('blockers',[]),{'code':code,'scope':self.state.get('journal',{}).get('phase','PREPARATION')}]);self._save();return self.read()
        finally:self.lock.release()
    def start(self):
        if self.thread:return
        def work():
            while not self.stop.is_set():
                action=self.command;self.command=None;self.wake.clear()
                self.run_once(apply=(action=='apply' or action!='preview' and self.policy['enabled']))
                self.wake.wait(300)
        self.thread=Thread(target=work,name='owner-data-maintenance',daemon=True);self.thread.start()
    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join(10)

class MaintenanceRouter:
    def __init__(self,service):self.service=service
    def start_maintenance(self):self.service.start()
    def close(self):self.service.close()
    def accepts_post(self,path):return path in ('/api/system/maintenance/preview','/api/system/maintenance/apply','/api/system/maintenance/enable')
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/api/system/maintenance':return 200,self.service.read(),None
        if method=='POST' and self.accepts_post(path):return 202,self.service.request(path.rsplit('/',1)[-1],payload),None
        return None
