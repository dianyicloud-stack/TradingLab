"""Market fact owner expiry; no watchlist, native rules or processed cursor reset."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from shared.storage.maintenance import snapshot
from contracts.live.market_agent import AgentError
from contracts.maintenance import SNAPSHOT_OPTIONS

def prune(state,ids):
    state=deepcopy(state);ids=set(ids)
    state['archived_sessions']=[s for s in state.get('archived_sessions',[]) if s.get('tracking_session_id') not in ids]
    state.setdefault('eventEngine',{})['events']=[e for e in state.get('eventEngine',{}).get('events',[]) if e.get('tracking_session_id') not in ids]
    # Only old sessions (not current watch entries) are eligible; counters and
    # analysis/decision checkpoint stay intact as the durable consumption boundary.
    state.setdefault('store',{})['sessions']={k:s for k,s in state.get('store',{}).get('sessions',{}).items() if s.get('tracking_session_id') not in ids}
    return state

class AgentRetention:
    def __init__(self,service):self.service=service;self.repo=service.repo

    def identity(self):
        with self.repo.connect() as db:identity=db.execute('SELECT identity FROM retention_identity WHERE id=1').fetchone()[0]
        return {'owner':'MARKET_DATA_AGENT','source':self.service.source,'root':str(self.service.root),'generation':identity,
                'validation_version':'NATIVE_BASELINE_V2','native_sha256':hashlib.sha256(Path(__file__).with_name('native_core.mjs').read_bytes()).hexdigest()}

    def effective_day(self,now):
        day=now.astimezone(timezone(timedelta(hours=8))).date()
        if not self.service.calendar:raise AgentError('CALENDAR_NOT_READY')
        for _ in range(16):
            if self.service.calendar(day.isoformat()):return day.isoformat()
            day-=timedelta(days=1)
        raise AgentError('CALENDAR_NOT_READY')

    @staticmethod
    def evidence_hash(value):
        return hashlib.sha256(json.dumps({k:value.get(k) for k in ('day','samples','daily_samples','volume_ratio_days','identity','session_scope','board_context','missing_board_context')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def valid(self,value,day,state):
        symbols={w['symbol'] for w in state.get('store',{}).get('watchlist',[]) if w.get('lifecycle_status')!='DROPPED'}
        sessions={s.get('tracking_session_id'):s for s in [*state.get('store',{}).get('sessions',{}).values(),*state.get('archived_sessions',[])]}
        if not value:return False
        for w in state.get('store',{}).get('watchlist',[]):
            if w.get('lifecycle_status')=='DROPPED':continue
            sid=value.get('session_scope',{}).get(w['symbol']);s=sessions.get(sid,{})
            if s.get('date')!=day or s.get('symbol')!=w['symbol'] or not s.get('rows'):return False
            current=sessions.get(w.get('tracking_session_id'),{})
            if current.get('date')==day and w.get('tracking_session_id')!=sid:return False
        return bool(value and value.get('ready') is True and value.get('day')==day and value.get('identity')==self.identity()
            and value.get('evidence_hash')==self.evidence_hash(value) and symbols==set(value.get('samples',{}))
            and value.get('volume_ratio_days')==state.get('store',{}).get('volumeRatioDays',20)
            and all(value['samples'].get(s) and value.get('daily_samples',{}).get(day+'|'+s+'|daily') for s in symbols))

    def validation(self):
        with self.repo.connect() as db:row=db.execute('SELECT payload FROM retention_validation WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {'status':'NOT_CHECKED','missing':[]}

    def prepare(self,now,state=None,*,fetch=True,force=False):
        """Owner startup/cycle/explicit command only. GET never calls this writer."""
        state=state or self.repo.checkpoint()[1]
        try:day=self.effective_day(now)
        except Exception as e:return self._record_validation({'status':'FAILED','reason':getattr(e,'code','CALENDAR_NOT_READY'),'missing':[],'checked_at':now.isoformat()})
        with self.repo.connect() as db:old=db.execute('SELECT payload FROM retention_readiness WHERE id=1').fetchone()
        saved=json.loads(old[0]) if old else None;valid=self.valid(saved,day,state)
        key=(day,json.dumps(self.identity(),sort_keys=True),tuple(sorted(w['symbol'] for w in state.get('store',{}).get('watchlist',[]) if w.get('lifecycle_status')!='DROPPED')))
        if valid and getattr(self.service,'_retention_prepared',None)==key and not force:return self.validation()
        # Network retries are bounded; startup still inspects/restores without network.
        last=getattr(self.service,'_retention_attempt',None)
        if fetch and not force and last and last[0]==key and (now-last[1]).total_seconds()<300:return self.validation()
        if fetch:self.service._retention_attempt=(key,now)
        try:
            value=self.service.worker.call({'op':'maintenance_baselines','day':day,'now':now.isoformat(),'prepare':fetch and day==now.astimezone(timezone(timedelta(hours=8))).date().isoformat(),'restore':saved if valid else None})
        except Exception as e:return self._record_validation({'status':'FAILED','reason':getattr(e,'code','NATIVE_BASELINE_VALIDATION_FAILED'),'missing':[],'checked_at':now.isoformat(),'day':day})
        status={'status':'PASSED' if value.get('ready') else 'FAILED','day':day,'checked_at':now.isoformat(),'missing':value.get('missing',[]),'identity':self.identity()}
        if value.get('ready'):
            value['identity']=self.identity();value['evidence_hash']=self.evidence_hash(value)
            value['ranges']={s:{'count':len(rows),'from':min(str(r.get('date','')) for r in rows),'through':max(str(r.get('date','')) for r in rows)} for s,rows in value['samples'].items()}
            with self.repo.connect() as db:db.execute('INSERT INTO retention_readiness VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET day=excluded.day,payload=excluded.payload',(day,json.dumps(value,ensure_ascii=False)))
            self.service._retention_prepared=key
            status['evidence_hash']=value['evidence_hash'];status['ranges']=value['ranges']
        return self._record_validation(status)

    def _record_validation(self,value):
        with self.repo.connect() as db:db.execute('INSERT INTO retention_validation VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(json.dumps(value,ensure_ascii=False),))
        return value

    def plan(self,protected=()):
        with self.repo.connect() as db:
            ready=db.execute('SELECT day,payload FROM retention_readiness WHERE id=1').fetchone()
        if not ready:return {'owner':'MARKET_AGENT','blocked':True,'reason':'NEW_DAY_OR_LOOKBACK_NOT_READY','records':0,'estimated_logical_bytes':0,'validation':self.validation()}
        day=ready[0];_,state=self.repo.checkpoint()
        expected=self.effective_day(self.service.clock())
        if day!=expected or not self.valid(json.loads(ready[1]),expected,state):
            return {'owner':'MARKET_AGENT','blocked':True,'reason':'READINESS_CERTIFICATE_INVALID','records':0,'estimated_logical_bytes':0,'validation':{**self.validation(),'status':'FAILED','reason':'DATE_IDENTITY_OR_VERSION_MISMATCH'}}
        sessions={s['tracking_session_id']:s for s in [*state.get('store',{}).get('sessions',{}).values(),*state.get('archived_sessions',[])]}
        # Native formal snapshots are immutable references and kept independently.
        formal=[f for f in self.repo.facts() if f['kind'] in ('HANDOFF','ACK_RECEIPT')]
        blocked=set(protected)
        for sid in sessions:
            if any(sid in json.dumps(f['payload']) for f in formal):blocked.add(sid)
        ids={sid for sid,s in sessions.items() if s.get('date') and s['date']<day and sid not in blocked}
        # Continue a partially deleted session after checkpoint pruning.
        with self.repo.connect() as db:ids.update(r[0] for r in db.execute('SELECT session_id FROM expired_fact_sessions WHERE keep_day<=?',(day,)))
        ids.difference_update(blocked)
        rows=[]
        for f in self.repo.facts():
            if f['kind'] in ('SESSION','SNAPSHOT','OBSERVATION','EVENT','GAP') and (f['payload'].get('tracking_session_id') or f['payload'].get('session')) in ids:
                rows.append({'seq':f['seq'],'kind':f['kind'],'bytes':len(json.dumps(f['payload'],ensure_ascii=False).encode())})
        return {'owner':'MARKET_AGENT','keep_day':day,'records':len(rows),'estimated_logical_bytes':sum(r['bytes'] for r in rows),'rows':rows,
                'sessions':sorted(ids),'protected_sessions':sorted(blocked),'blocked':False,'validation':{**self.validation(),'status':'PASSED'},'lookback':{'volume_ratio_days':json.loads(ready[1]).get('volume_ratio_days'),'baseline_saved':True}}

    def command(self,payload):
        service=self.service
        if self.repo.path.absolute()!=self.repo.path.resolve():raise AgentError('MAINTENANCE_REPARSE_POINT')
        with service.lock:
            if payload['action']=='RETENTION_VALIDATE':
                if payload.get('confirmation')!='VALIDATE_NATIVE_BASELINES':raise AgentError('RETENTION_CONFIRMATION_REQUIRED')
                return self.prepare(service.clock(),force=True)
            plan=self.plan(payload.get('protected_sessions',()))
            if payload['action']=='RETENTION_PREVIEW':
                from shared.storage.maintenance import snapshot_preflight
                return {**plan,'storage':snapshot_preflight(service.root,{'market_agent.db':self.repo.path},**SNAPSHOT_OPTIONS)}
            if payload.get('confirmation')!='OWNER_RETENTION_V1':raise AgentError('RETENTION_CONFIRMATION_REQUIRED')
            if plan.get('blocked') or payload.get('keep_day')!=plan['keep_day']:raise AgentError('RETENTION_NOT_READY')
            run=payload.get('run_id','')
            if run!='retain-'+plan['keep_day']:raise AgentError('RETENTION_RUN_INVALID')
            if payload['action']=='RETENTION_BACKUP':return snapshot(service.root,{'market_agent.db':service.root/'market_agent.db'},run,**SNAPSHOT_OPTIONS)
            if payload['action']!='RETENTION_APPLY':raise AgentError('RETENTION_ACTION_INVALID')
            # Require a verified owner snapshot before the first/batched mutation.
            verified=getattr(service,'_retention_backups',set())
            if run not in verified:
                snapshot(service.root,{'market_agent.db':service.root/'market_agent.db'},run,**SNAPSHOT_OPTIONS);verified.add(run);service._retention_backups=verified
            rows=plan['rows'][:100]
            with self.repo.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.executemany('INSERT OR IGNORE INTO expired_fact_sessions VALUES(?,?)',[(s,plan['keep_day']) for s in plan['sessions']])
                trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='facts_no_delete'").fetchone()
                if trigger:db.execute('DROP TRIGGER facts_no_delete')
                db.executemany('DELETE FROM facts WHERE seq=?',[(r['seq'],) for r in rows])
                if trigger:db.execute(trigger[0])
                current=json.loads(db.execute('SELECT state FROM checkpoint WHERE id=1').fetchone()[0]);state=prune(current,plan['sessions'])
                db.execute('UPDATE checkpoint SET state=?,version=version+1 WHERE id=1',(json.dumps(state,ensure_ascii=False),))
            service.worker.call({'op':'maintenance_prune','sessions':plan['sessions'],'keep_day':plan['keep_day']});service._publish()
            return {'status':'MORE' if rows else 'DONE','logical_records_deleted':len(rows),'keep_day':plan['keep_day']}
