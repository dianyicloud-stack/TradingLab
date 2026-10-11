"""Independent source service; UI reads immutable snapshots, never drives cycles."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from threading import Thread,RLock,Event
from queue import Queue,Empty
from copy import deepcopy
import os,shutil,subprocess,json,time
from contracts.live.market_agent import AgentError,COMMANDS
from .repository import AgentRepository,digest

NODE_VERSION='v24.19.0'
TZ=timezone(timedelta(hours=8))

def node_path():
    configured=os.environ.get('TRADING_LAB_NODE')
    candidate=configured or shutil.which('node')
    if not candidate:raise AgentError('NODE_RUNTIME_MISSING','需要 Node 24.19.0；配置 TRADING_LAB_NODE。')
    version=subprocess.run([candidate,'--version'],capture_output=True,text=True,timeout=10,check=True).stdout.strip()
    if version!=NODE_VERSION:raise AgentError('NODE_VERSION_MISMATCH',f'需要 {NODE_VERSION}，实际 {version}')
    return candidate

class CoreWorker:
    def __init__(self,state,network=False,directory=None,now=None):
        self.process=subprocess.Popen([node_path(),str(Path(__file__).with_name('worker.mjs'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.output=Queue();Thread(target=self._read,daemon=True).start();self.call({'op':'initialize','state':state,'network':network,'directory_path':str(directory) if directory else None,'now':now})
    def _read(self):
        for line in self.process.stdout:self.output.put(line)
        self.output.put(None)
    def call(self,payload):
        if self.process.poll() is not None:raise AgentError('AGENT_WORKER_EXITED')
        self.process.stdin.write(json.dumps(payload,ensure_ascii=False)+'\n');self.process.stdin.flush()
        try:line=self.output.get(timeout=90)
        except Empty:self.close();raise AgentError('AGENT_WORKER_TIMEOUT') from None
        if line is None:raise AgentError('AGENT_WORKER_EXITED')
        result=json.loads(line)
        if not result['ok']:raise AgentError(result.get('code','AGENT_CORE_ERROR'),result['error'])
        return result['value']
    def close(self):
        if not self.process.stdin.closed:self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Owner-local disposable computation worker; no AI, account or external writes.
            self.process.kill();self.process.wait(timeout=10)
        for stream in (self.process.stdout,self.process.stderr):
            if stream:stream.close()

class AgentService:
    def __init__(self,root,*,source='TEST',network=False,calendar=None,clock=None):
        if source not in ('USER','TEST'):raise AgentError('AGENT_CONTEXT_INVALID')
        self.root=Path(root).resolve();self.source=source;self.network=network
        import hashlib
        self.build_id=hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in ('service.py','repository.py','runtime.mjs','retention.py','native_core.mjs'))).hexdigest()[:16]
        self.repo=AgentRepository(root);self.lock=RLock();self.stop_event=Event();self.thread=None;self.running=False;self.test_frames=None
        self.clock=clock or (lambda:datetime.now(TZ));self.calendar=calendar
        self.worker=CoreWorker(self.repo.checkpoint()[1],network,None,self.clock().isoformat());self.errors=[];self.restarts=0;self.last_cycle=None;self.last_seconds=None
        self._view={};self._publish()
        from .retention import AgentRetention
        AgentRetention(self).prepare(self.clock(),fetch=False)
    def _reset(self):
        self.worker.close();self.worker=CoreWorker(self.repo.checkpoint()[1],self.network,None,self.clock().isoformat())
    def metadata(self,payload):
        if payload.get('source')!=self.source or payload.get('schema_version')!='1.0':raise AgentError('COMMAND_CONTEXT_INVALID')
        if not self.network:raise AgentError('MARKET_NETWORK_NOT_AUTHORIZED','当前未启用外部行情查询。',503)
        with self.lock:return self.worker.call({'op':'metadata','symbol':payload.get('symbol'),'now':self.clock().isoformat()})
    def command(self,payload):
        if not isinstance(payload,dict) or payload.get('schema_version')!='1.0' or payload.get('source')!=self.source:raise AgentError('COMMAND_CONTEXT_INVALID',status=400)
        if payload.get('action') in ('RETENTION_PREVIEW','RETENTION_BACKUP','RETENTION_APPLY','RETENTION_VALIDATE'):
            from .retention import AgentRetention
            return AgentRetention(self).command(payload)
        if payload.get('action') in ('DELETE_PLAN','DELETE'):
            from .tracking_delete import TrackingDeletion
            owner=TrackingDeletion(self)
            if payload['action']=='DELETE_PLAN':
                with self.lock:return owner.plan(payload.get('symbol',''),deepcopy(payload.get('protected_references',{})))
            return owner.execute(payload)
        if payload.get('action') not in COMMANDS or not isinstance(payload.get('command_id'),str) or not 1<=len(payload['command_id'])<=100 or type(payload.get('expected_version')) is not int:raise AgentError('COMMAND_INVALID',status=400)
        with self.lock:
            previous=self.repo.replay(payload)
            if previous:return previous
            version=self.repo.command_version()
            if payload['expected_version']!=version:raise AgentError('VERSION_CONFLICT')
            try:
                if payload['action']=='IMMEDIATE':
                    if not any(s['symbol']==payload.get('symbol') and s['date']==self.clock().date().isoformat() and s.get('lifecycle_status')!='DROPPED' for s in self.query()['sessions']):raise AgentError('TRACKING_NOT_FOUND')
                    self.cycle(self.test_frames if self.source=='TEST' else None,immediate_symbol=payload['symbol'])
                    if self.errors:raise AgentError('IMMEDIATE_OBSERVATION_FAILED',self.errors[0]['message'])
                    state=self.repo.checkpoint()[1]
                else:state=self.worker.call({'op':'command',**{k:v for k,v in payload.items() if k in ('symbol','action','name','board','volume_ratio_days','reserved_session_ids')},'now':self.clock().isoformat()})
                result=self.repo.commit(state,self._session_records(state),command=payload,expected=version);self._publish();return result
            except Exception:self._reset();raise
    def _session_records(self,state):return [('SESSION',s['tracking_session_id'],s) for s in [*state.get('store',{}).get('sessions',{}).values(),*state.get('archived_sessions',[])]]
    def cycle(self,frames=None,*,immediate_symbol=None):
        if frames is not None and self.source!='TEST':raise AgentError('TEST_INPUT_REJECTED')
        if frames is not None:self.test_frames=frames
        with self.lock:
            started=time.monotonic();now=self.clock();market_open=bool(self.calendar and self.calendar(now.date().isoformat()))
            try:
                value=self.worker.call({'op':'cycle','now':now.isoformat(),'market_open':market_open,'frames':frames or {},'immediate_symbol':immediate_symbol})
                state=value['state'];records=self._session_records(state)
                records.extend(('EVENT',e['event_id'],e) for e in state.get('eventEngine',{}).get('events',[]))
                records.extend(('OBSERVATION',r['tracking_session_id']+':'+r['raw']['id'],r) for r in value.get('observations',[]))
                for r in value['snapshots']:
                    sample=r['sample'];key=r['tracking_session_id']+':'+str(sample.get('source_updated_at'))+':'+str(sample.get('trade_source_captured_at'))
                    # Same cached source times are the same sample identity, never a new market tick.
                    old=next((x for x in reversed(self.repo.facts('SNAPSHOT')) if x['identity']==key),None)
                    if not old:records.append(('SNAPSHOT',key,r))
                records.extend(('GAP',digest(g),g) for g in value['gaps'])
                self.repo.commit(state,records);self.errors=value['errors'];self.last_cycle=now.isoformat();self.last_seconds=time.monotonic()-started;self._publish()
                from .retention import AgentRetention
                AgentRetention(self).prepare(now,state)
            except Exception as error:
                self.errors=[{'code':getattr(error,'code','AGENT_ERROR'),'message':str(error)}];self._reset();self._publish();raise
    def _publish(self):
        version,state=self.repo.checkpoint();facts=self.repo.facts();latest={}
        for row in facts:latest[(row['kind'],row['identity'])]=row
        sessions=[*state.get('store',{}).get('sessions',{}).values(),*state.get('archived_sessions',[])]
        self._view={'schema_version':'1.0','build_id':self.build_id,'version':self.repo.command_version(),'fact_version':version,'source':self.source,'status':'ERROR' if self.errors else 'READY',
            'capabilities':['TRACKING_DELETE_V1','DAILY_RETENTION_V1','RETENTION_VALIDATION_V2'],
            'agent_state':'RUNNING' if self.running and not self.stop_event.is_set() else 'STOPPED',
            'last_cycle_at':self.last_cycle,'actual_cycle_seconds':self.last_seconds,'target_interval_seconds':5,
            'errors':deepcopy(self.errors),'sessions':sessions,'facts':list(latest.values()),
            'analysis_state':state.get('eventEngine',{}).get('analysisState',{}),
            'trading_date':self.clock().date().isoformat(),'event_statuses':state.get('event_statuses',{}),
            'parameters':{'volume_ratio_days':state.get('store',{}).get('volumeRatioDays',20)},
            'ai_calls':0,'orders':0}
    def query(self):return deepcopy(self._view)
    def start(self,frame_source=None,interval=5):
        if self.thread and self.thread.is_alive():return
        if frame_source and self.source!='TEST':raise AgentError('TEST_INPUT_REJECTED')
        self.stop_event.clear();self.scheduler_error=None
        self.running=True;self._publish()
        def run():
            self.running=True
            try:
                while not self.stop_event.is_set():
                    started=time.monotonic()
                    try:self.cycle(frame_source() if frame_source else None);self.restarts=0
                    except Exception as error:
                        self.restarts+=1
                        self.scheduler_error=getattr(error,'code',type(error).__name__)
                        if self.restarts>=5:self.scheduler_error='AUTO_RECOVERY_PAUSED:'+self.scheduler_error;break
                    now=self.clock();minute=now.hour*60+now.minute
                    try:active=bool(self.calendar and self.calendar(now.date().isoformat())) and (565<=minute<=690 or 780<=minute<=905)
                    except Exception:self.scheduler_error='CALENDAR_UNAVAILABLE';active=False
                    target=interval if active or self.source=='TEST' else max(20,interval)
                    delay=max(.05,target-(time.monotonic()-started)) if not self.errors else min(30,5*max(1,self.restarts))
                    self.stop_event.wait(delay)
            finally:self.running=False;self._publish()
        self.thread=Thread(target=run,name='market-agent-scheduler',daemon=True);self.thread.start()
    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join() # Controller reports bounded waiting; never closes an in-use worker.
        self.worker.close()
