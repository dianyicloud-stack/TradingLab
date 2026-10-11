"""Owner-only tracking deletion, consistent backup and retained audit references."""
from copy import deepcopy
from collections import Counter
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,re,sqlite3
from contracts.live.market_agent import AgentError
from .repository import digest,encode


def scrub(state,sessions):
    """Retire exact session identities, preserving allocation counters and protocols."""
    state=deepcopy(state);ids=set(sessions)
    symbols={s['symbol'] for s in [*state.get('store',{}).get('sessions',{}).values(),*state.get('archived_sessions',[])] if s.get('tracking_session_id') in ids}
    def clean(value):
        if isinstance(value,list):return [clean(v) for v in value if not isinstance(v,dict) or v.get('tracking_session_id') not in ids]
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ids and k not in symbols}
        return value
    store=state.setdefault('store',{});counters=deepcopy(store.get('session_seq_by_symbol',{}))
    for identity in ids:
        match=re.fullmatch(r'TS-(\d{4})(\d{2})(\d{2})-((?:sh|sz|bj)\d{6})-(\d+)',identity)
        if match:
            y,m,d,s,n=match.groups();key=f'{y}-{m}-{d}|{s}';counters[key]=max(counters.get(key,0),int(n))
    protocols={k:deepcopy(state.get('eventEngine',{}).get(k)) for k in ('handoffHistory','activeHandoff') if k in state.get('eventEngine',{})}
    state=clean(state);state['store']['session_seq_by_symbol']=counters
    state['store']['watchlist']=[w for w in store.get('watchlist',[]) if w.get('tracking_session_id') not in ids]
    state.setdefault('eventEngine',{}).update(protocols)
    return state


class TrackingDeletion:
    def __init__(self,service):self.service=service;self.repo=service.repo

    def plan(self,symbol,references):
        if not re.fullmatch(r'(sh|sz|bj)\d{6}',symbol):raise AgentError('INVALID_SYMBOL')
        version,state=self.repo.checkpoint()
        sessions=[s['tracking_session_id'] for s in [*state.get('store',{}).get('sessions',{}).values(),*state.get('archived_sessions',[])] if s.get('symbol')==symbol]
        facts=self.repo.facts();target=[f for f in facts if (f['payload'].get('tracking_session_id') or f['payload'].get('session')) in sessions or f['payload'].get('symbol')==symbol]
        # Formal owner references are discovered locally, never supplied by UI.
        for f in facts:
            if f['kind'] in ('HANDOFF','ACK_RECEIPT'):
                for identity in sessions:
                    if identity in encode(f['payload']):references.setdefault(identity,[]).append(f['kind']+':'+f['identity'])
        protected={s:sorted(set(v)) for s,v in references.items() if s in sessions and v}
        rows=[f for f in target if f['kind'] in ('SESSION','OBSERVATION','EVENT','SNAPSHOT','GAP')]
        body={'symbol':symbol,'sessions':sorted(set(sessions)),'protected_sessions':protected,
            'delete_counts':dict(Counter(f['kind'] for f in rows if f['payload'].get('tracking_session_id') not in protected)),
            'archive_counts':dict(Counter(f['kind'] for f in rows if f['payload'].get('tracking_session_id') in protected)),
            'fact_ids':[f['seq'] for f in rows],'command_version':self.repo.command_version(),
            'fact_set_hash':digest([(f['seq'],f['sha256']) for f in rows])}
        return {**body,'plan_hash':digest(body)}

    def execute(self,payload):
        service=self.service
        if payload.get('schema_version')!='1.0' or payload.get('source')!=service.source or payload.get('confirmation')!='DELETE_TRACKING_DATA':raise AgentError('DELETE_CONFIRMATION_REQUIRED')
        identity=payload.get('command_id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identity):raise AgentError('COMMAND_INVALID')
        references=payload.get('protected_references')
        if not isinstance(references,dict) or any(not isinstance(v,list) or any(not isinstance(x,str) for x in v) for v in references.values()):raise AgentError('REFERENCE_AUDIT_REQUIRED')
        with service.lock:
            previous=self.repo.replay(payload)
            if previous:
                service._reset();service._publish();return previous
            if payload.get('expected_version')!=self.repo.command_version():raise AgentError('VERSION_CONFLICT')
            plan=self.plan(payload['symbol'],deepcopy(references))
            if payload.get('plan_hash')!=plan['plan_hash']:raise AgentError('DELETE_PLAN_CHANGED')
            backup=service.root/'audit'/'tracking-deletions'/identity
            backup.mkdir(parents=True,exist_ok=True)
            with self.repo.connect() as source,closing(sqlite3.connect(backup/'market_agent.db')) as dest:source.backup(dest)
            manifest={**plan,'backup_sha256':hashlib.sha256((backup/'market_agent.db').read_bytes()).hexdigest()}
            import shutil
            native=service.root/'native_protocol'
            if native.exists():shutil.copytree(native,backup/'native_protocol',dirs_exist_ok=True)
            manifest['native_protocol_hashes']={str(p.relative_to(backup)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (backup/'native_protocol').rglob('*') if p.is_file()}
            (backup/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            with self.repo.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                state=json.loads(db.execute('SELECT state FROM checkpoint WHERE id=1').fetchone()[0])
                for sid in plan['sessions']:db.execute('INSERT OR IGNORE INTO retired_tracking_sessions VALUES(?,?,?)',(sid,payload['symbol'],identity))
                ids=[r[0] for r in db.execute('SELECT session_id FROM retired_tracking_sessions')]
                for seq in plan['fact_ids']:
                    row=db.execute('SELECT seq,kind,identity,revision,sha256,payload,recorded_at FROM facts WHERE seq=?',(seq,)).fetchone()
                    value=json.loads(row[5])
                    if value.get('tracking_session_id') in plan['protected_sessions']:
                        db.execute('INSERT OR IGNORE INTO protected_tracking_facts VALUES(?,?)',(seq,encode(dict(zip(('seq','kind','identity','revision','sha256','payload','recorded_at'),row)))))
                # DDL is transactional: a crash cannot leave the immutable guard off.
                db.execute('DROP TRIGGER facts_no_delete')
                db.executemany('DELETE FROM facts WHERE seq=?',[(i,) for i in plan['fact_ids']])
                db.execute("CREATE TRIGGER facts_no_delete BEFORE DELETE ON facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_MARKET_FACT');END")
                db.execute('UPDATE checkpoint SET version=version+1,state=? WHERE id=1',(encode(scrub(state,ids)),))
                db.execute('UPDATE command_version SET version=version+1 WHERE id=1')
                version=db.execute('SELECT version FROM command_version').fetchone()[0]
                result={'status':'DELETED','version':version,'symbol':payload['symbol'],'sessions':plan['sessions'],
                    'deleted':plan['delete_counts'],'protected':plan['archive_counts'],'protected_references':plan['protected_sessions'],
                    'backup':str(backup),'backup_sha256':manifest['backup_sha256']}
                db.execute('INSERT INTO commands VALUES(?,?,?)',(identity,digest(payload),encode(result)))
            # Replace only the owner's child projection after commit. The Agent
            # process/lease remains authoritative; no second writer is created.
            service._reset();service._publish()
            return result
