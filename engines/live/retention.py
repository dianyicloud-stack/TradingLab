"""Advisory owner maintenance. Keeps identity/cursors; expires only old detail."""
import json,hashlib,sqlite3
from contextlib import closing
from datetime import datetime,timezone
from shared.storage.maintenance import snapshot
from contracts.maintenance import SNAPSHOT_OPTIONS

TERMINAL={'COMPLETED','FAILED','CANCELLED','INTERRUPTED','SUPERSEDED'}

class LiveRetention:
    def __init__(self,service):self.service=service;self.runtime=service.runtime;self.opinions=service.opinions

    def busy(self):
        with self.runtime.connect(True) as db:
            return bool(db.execute("SELECT 1 FROM live_analysis_requests WHERE status IN ('RUNNING','QUEUED') LIMIT 1").fetchone() or
                        db.execute("SELECT 1 FROM advisory_coordinator WHERE state='RUNNING' OR pending>0 LIMIT 1").fetchone())

    def preview(self,boundary):
        protected=set(boundary.protected_opinions);sessions=set(boundary.protected_sessions);rows=[]
        with self.opinions.connect(True) as db:
            for r in db.execute('SELECT o.advisory_id,o.input_id,o.session_date,o.tracking_session_id,length(cast(o.payload as blob))+length(cast(i.payload as blob)) AS bytes FROM advisory_opinions o JOIN advisory_inputs i USING(input_id) WHERE o.session_date<?',(boundary.keep_day,)):
                rows.append({'id':r['advisory_id'],'input_id':r['input_id'],'date':r['session_date'],'bytes':r['bytes'],
                             'keep_reason':'ACCOUNT_OR_MANUAL_REFERENCE' if r['advisory_id'] in protected or r['tracking_session_id'] in sessions else None})
        with self.runtime.connect(True) as db:
            groups=[dict(r) for r in db.execute("SELECT session_id, count(*) AS records,sum(length(cast(payload as blob))) AS bytes FROM live_ingested_facts GROUP BY session_id")]
            expired=[]
            for r in db.execute('SELECT session_id,payload FROM live_ingestion'):
                day=json.loads(r['payload']).get('session',{}).get('session_date')
                if day and day<boundary.keep_day and r['session_id'] not in sessions:expired.append(r['session_id'])
            tasks=[]
            for r in db.execute('SELECT request_id,status,payload FROM live_analysis_requests'):
                p=json.loads(r['payload']);day=p.get('frozen',{}).get('session_date') or str(p.get('task',{}).get('created_at',''))[:10]
                if day and day<boundary.keep_day and r['status'] in TERMINAL and not p.get('detail_expired'):
                    tasks.append({'id':r['request_id'],'bytes':len(r['payload'].encode()),'date':day})
        return {'owner':'LIVE_ADVISORY','keep_day':boundary.keep_day,'opinions':rows,'expired_sessions':expired,'tasks':tasks,
                'records':sum(not r['keep_reason'] for r in rows)+len(tasks)+sum(r['records'] for r in groups if r['session_id'] in expired),
                'estimated_logical_bytes':sum(r['bytes'] for r in rows if not r['keep_reason'])+sum(r['bytes'] for r in tasks)+sum(r['bytes'] or 0 for r in groups if r['session_id'] in expired),
                'blocked':self.busy(),'reason':'ACTIVE_OR_QUEUED_TASK' if self.busy() else None}

    def snapshot(self,run_id):
        r=self.runtime.store.path('advisory_runtime.db');o=self.opinions.store.path('advisory.db');p=self.opinions.store.path('provider_requests/provider_requests.db')
        return {'runtime':snapshot(r.parent,{'advisory_runtime.db':r},run_id,**SNAPSHOT_OPTIONS),
                'opinions':snapshot(o.parent,{'advisory.db':o,'provider_requests.db':p},run_id,**SNAPSHOT_OPTIONS)}

    def compact_offline(self):
        from shared.storage.maintenance import compact_database
        if self.busy():raise ValueError('ACTIVE_OR_QUEUED_TASK')
        paths=(self.runtime.store.path('advisory_runtime.db'),self.opinions.store.path('advisory.db'),self.opinions.store.path('provider_requests/provider_requests.db'))
        return [compact_database(p.parent,p) for p in paths if p.exists()]

    def snapshot_requirements(self):
        from shared.storage.maintenance import snapshot_preflight
        r=self.runtime.store.path('advisory_runtime.db');o=self.opinions.store.path('advisory.db');p=self.opinions.store.path('provider_requests/provider_requests.db')
        files={'advisory.db':o}
        if p.exists():files['provider_requests.db']=p
        return {'runtime':snapshot_preflight(r.parent,{'advisory_runtime.db':r},**SNAPSHOT_OPTIONS),
                'opinions':snapshot_preflight(o.parent,files,**SNAPSHOT_OPTIONS)}

    def step(self,boundary,limit=100):
        # The same gate used by scheduling protects the entire maintenance batch.
        with self.service._locks_guard:
            if self.busy():return {'status':'DEFERRED','reason':'ACTIVE_OR_QUEUED_TASK'}
            plan=self.preview(boundary);deleted=0
            eligible=[r for r in plan['opinions'] if not r['keep_reason']][:limit]
            with self.opinions.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS retention_tombstones(advisory_id TEXT PRIMARY KEY,input_id TEXT,session_date TEXT,cleaned_at TEXT)')
                triggers=db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN ('advisory_opinions_no_delete','advisory_inputs_no_delete')").fetchall()
                for r in triggers:db.execute('DROP TRIGGER '+r['name'])
                for r in eligible:
                    db.execute('INSERT OR IGNORE INTO retention_tombstones VALUES(?,?,?,?)',(r['id'],r['input_id'],r['date'],datetime.now(timezone.utc).isoformat()))
                    db.execute('DELETE FROM advisory_opinions WHERE advisory_id=?',(r['id'],));db.execute('DELETE FROM advisory_inputs WHERE input_id=?',(r['input_id'],));deleted+=1
                for r in triggers:db.execute(r['sql'])
            # Reconcile committed markers on restart, including a crash between owners.
            from engines.live.provider_request_repository import expire_inputs
            with self.opinions.connect(True) as db:expired_inputs=[r[0] for r in db.execute('SELECT input_id FROM retention_tombstones')]
            expire_inputs(self.opinions.store.path('provider_requests/provider_requests.db'),expired_inputs)
            with self.runtime.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS live_expired_sessions(session_id TEXT PRIMARY KEY,keep_day TEXT NOT NULL)')
                for sid in plan['expired_sessions']:
                    db.execute('INSERT OR IGNORE INTO live_expired_sessions VALUES(?,?)',(sid,boundary.keep_day))
                    ids=[r[0] for r in db.execute('SELECT rowid FROM live_ingested_facts WHERE session_id=? LIMIT ?',(sid,limit))]
                    db.executemany('DELETE FROM live_ingested_facts WHERE rowid=?',[(r,) for r in ids]);deleted+=len(ids)
                    if not ids:
                        for table in ('live_ingestion','native_control'):db.execute('DELETE FROM '+table+' WHERE session_id=?',(sid,))
                        db.execute('DELETE FROM advisory_pending WHERE tracking_session_id=?',(sid,))
                for r in plan['tasks'][:limit]:
                    row=db.execute('SELECT payload,status FROM live_analysis_requests WHERE request_id=?',(r['id'],)).fetchone();p=json.loads(row['payload'])
                    # Preserve task id, order, status and hashes; never invent a success.
                    compact={'task':p.get('task',{}),'detail_expired':True,'input_id':p.get('frozen',{}).get('input_id'),'input_hash':p.get('frozen',{}).get('input_hash'),'session_date':p.get('frozen',{}).get('session_date')}
                    db.execute('UPDATE live_analysis_requests SET payload=? WHERE request_id=?',(json.dumps(compact,ensure_ascii=False),r['id']));deleted+=1
            with self.runtime.connect(True) as db:
                ids=[r[0] for r in db.execute("SELECT json_extract(payload,'$.input_id') FROM live_analysis_requests WHERE json_extract(payload,'$.detail_expired')=1") if r[0]]
            expire_inputs(self.opinions.store.path('provider_requests/provider_requests.db'),[i for i in ids if self.opinions.input(i) is None])
            return {'status':'MORE' if deleted else 'DONE','logical_records_deleted_or_compacted':deleted,'keep_day':boundary.keep_day}
