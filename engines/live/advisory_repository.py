"""Domain-owned M2.2 stores: LIVE runtime is mutable; advisory facts are append-only."""
from contextlib import contextmanager
import json
import sqlite3
from shared.serialization import canonical


class AdvisoryRuntimeRepository:
    def notification_boundary(self):
        with self.connect(True) as db:
            row=db.execute("SELECT seq FROM sqlite_sequence WHERE name='live_analysis_requests'").fetchone()
        return row[0] if row else 0

    def notification_completions(self,after,limit):
        with self.connect(True) as db:
            return [dict(r) for r in db.execute("SELECT sequence,status,json_extract(payload,'$.task.opinion_id') AS opinion_id FROM live_analysis_requests WHERE sequence>? ORDER BY sequence LIMIT ?",(after,min(100,max(1,limit))))]

    def __init__(self,store):
        self.store=store;store.ensure()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS advisory_settings(
                scope TEXT PRIMARY KEY, provider TEXT, model TEXT, reasoning_effort TEXT,
                auto_ai INTEGER, debounce_seconds REAL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS advisory_cursors(
                tracking_session_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, session_date TEXT NOT NULL,
                last_advised_event_seq INTEGER NOT NULL, last_advised_observation_time TEXT,
                last_advisory_id TEXT NOT NULL, last_input_hash TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS advisory_pending(
                tracking_session_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL,
                event_seq INTEGER NOT NULL, observation_time TEXT, input_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS advisory_coordinator(
                tracking_session_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('IDLE','RUNNING')),
                active_request_id TEXT, pending INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS advisory_failures(
                request_id TEXT PRIMARY KEY, tracking_session_id TEXT NOT NULL,
                symbol TEXT NOT NULL, error_code TEXT NOT NULL, detail TEXT,
                failed_at TEXT NOT NULL);''')
            db.execute('''CREATE TABLE IF NOT EXISTS portfolio_outcomes(
                advisory_id TEXT PRIMARY KEY, payload TEXT NOT NULL, recorded_at TEXT NOT NULL)''')
            db.executescript('''CREATE TABLE IF NOT EXISTS live_preferences(
                symbol TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS live_ingested_facts(
                session_id TEXT NOT NULL, kind TEXT NOT NULL, identity TEXT NOT NULL,
                payload TEXT NOT NULL, read_at TEXT NOT NULL,
                PRIMARY KEY(session_id,kind,identity));
                CREATE TABLE IF NOT EXISTS live_ingestion(
                session_id TEXT PRIMARY KEY, payload TEXT NOT NULL);''')
            db.executescript('''CREATE TABLE IF NOT EXISTS native_control(
                session_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(session_id,kind));
                CREATE TABLE IF NOT EXISTS advisory_provenance_audit(
                request_id TEXT PRIMARY KEY, payload TEXT NOT NULL);''')
            db.execute('''CREATE TABLE IF NOT EXISTS live_analysis_requests(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL, session_id TEXT NOT NULL, status TEXT NOT NULL,
                payload TEXT NOT NULL)''')
            db.executescript('''CREATE TABLE IF NOT EXISTS live_retired_sessions(session_id TEXT PRIMARY KEY, symbol TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tracking_deletion_intents(symbol TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL);''')
            db.execute('CREATE TABLE IF NOT EXISTS live_expired_sessions(session_id TEXT PRIMARY KEY,keep_day TEXT NOT NULL)')
            db.execute("UPDATE live_analysis_requests SET status='INTERRUPTED' WHERE status IN ('QUEUED','RUNNING')")
            columns={row[1] for row in db.execute('PRAGMA table_info(advisory_settings)')}
            additions=(('auto_ai_mode','TEXT'),('pin_order','INTEGER'),('fresh_seconds','INTEGER'),
                       ('delayed_seconds','INTEGER'),('important_event_types_json','TEXT'),('auto_event_types_json','TEXT'),('auto_event_max_age_seconds','INTEGER'))
            for name,kind in additions:
                if name not in columns:db.execute(f'ALTER TABLE advisory_settings ADD COLUMN {name} {kind}')
            failure_columns={row[1] for row in db.execute('PRAGMA table_info(advisory_failures)')}
            if 'source_hash' not in failure_columns:db.execute('ALTER TABLE advisory_failures ADD COLUMN source_hash TEXT')
            # A process restart cannot have a live provider call. Recover runtime
            # coordinator rows without touching any immutable Advisory fact.
            db.execute("UPDATE advisory_coordinator SET state='IDLE',active_request_id=NULL,pending=0 WHERE state='RUNNING'")

    @contextmanager
    def connect(self,readonly=False):
        path=self.store.path('advisory_runtime.db')
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) if readonly else sqlite3.connect(path,timeout=5)
        try:
            db.row_factory=sqlite3.Row
            if readonly:db.execute('PRAGMA query_only=ON')
            with db:yield db
        finally:db.close()

    def settings(self):
        with self.connect(True) as db:rows=db.execute('SELECT * FROM advisory_settings').fetchall()
        result={}
        for row in rows:
            value={k:(bool(row[k]) if k=='auto_ai' else row[k]) for k in row.keys()
                   if k not in ('scope','updated_at','important_event_types_json','auto_event_types_json') and row[k] is not None}
            if row['important_event_types_json'] is not None:value['important_event_types']=json.loads(row['important_event_types_json'])
            if row['auto_event_types_json'] is not None:value['auto_event_types']=json.loads(row['auto_event_types_json'])
            result[row['scope']]={**value,'updated_at':row['updated_at']}
        return result

    def save_setting(self,scope,value,stamp):
        columns=('scope','provider','model','reasoning_effort','auto_ai','debounce_seconds','updated_at',
                 'auto_ai_mode','pin_order','fresh_seconds','delayed_seconds','important_event_types_json','auto_event_types_json','auto_event_max_age_seconds')
        values={**value,'scope':scope,'updated_at':stamp,
                'auto_ai':None if 'auto_ai' not in value else int(value['auto_ai'])}
        for key in ('important_event_types','auto_event_types'):
            values[key+'_json']=json.dumps(value[key]) if value.get(key) is not None else None
        with self.connect() as db:
            db.execute('INSERT INTO advisory_settings ('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(scope) DO UPDATE SET '+
                       ','.join(k+'=excluded.'+k for k in columns if k!='scope'),tuple(values.get(k) for k in columns))

    def cursor(self,identity):
        with self.connect(True) as db:row=db.execute('SELECT * FROM advisory_cursors WHERE tracking_session_id=?',(identity,)).fetchone()
        return dict(row) if row else None

    def preferences(self,symbol):
        with self.connect(True) as db:
            row=db.execute('SELECT payload FROM live_preferences WHERE symbol=?',(symbol.lower(),)).fetchone()
        return json.loads(row[0]) if row else {}

    def retired(self,identity):
        with self.connect(True) as db:return db.execute('SELECT 1 FROM live_retired_sessions WHERE session_id=?',(identity,)).fetchone() is not None

    def expired(self,identity):
        with self.connect(True) as db:return db.execute('SELECT 1 FROM live_expired_sessions WHERE session_id=?',(identity,)).fetchone() is not None

    def retired_sessions(self):
        with self.connect(True) as db:return {r[0] for r in db.execute('SELECT session_id FROM live_retired_sessions')}

    def deletion_intent(self,symbol):
        with self.connect(True) as db:row=db.execute('SELECT payload,status FROM tracking_deletion_intents WHERE symbol=?',(symbol,)).fetchone()
        return {'payload':json.loads(row[0]),'status':row[1]} if row else None

    def begin_tracking_deletion(self,symbol,sessions,payload):
        from pathlib import Path
        from contextlib import closing
        import hashlib
        backup=self.store.path('tracking-deletions/'+payload['command_id']);backup.mkdir(parents=True,exist_ok=True)
        if not (backup/'manifest.json').exists():
            with self.connect(True) as source,closing(sqlite3.connect(backup/'advisory_runtime.db')) as target:source.backup(target)
            (backup/'manifest.json').write_text(canonical({'symbol':symbol,'sessions':sessions,'sha256':hashlib.sha256((backup/'advisory_runtime.db').read_bytes()).hexdigest()}),encoding='utf-8')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT INTO tracking_deletion_intents VALUES(?,?,'PENDING') ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload,status='PENDING'",(symbol,canonical(payload)))
            db.executemany('INSERT OR IGNORE INTO live_retired_sessions VALUES(?,?)',[(s,symbol) for s in sessions])
            db.execute("UPDATE live_analysis_requests SET status='CANCELLED' WHERE symbol=? AND status IN ('QUEUED','RUNNING')",(symbol,))
            db.execute('DELETE FROM live_preferences WHERE symbol=?',(symbol,))
            db.execute('DELETE FROM advisory_settings WHERE scope=?',('SYMBOL:'+symbol,))
            for sid in sessions:
                for table,column in (('advisory_pending','tracking_session_id'),('advisory_coordinator','tracking_session_id'),('live_ingestion','session_id'),('live_ingested_facts','session_id'),('native_control','session_id')):
                    db.execute(f'DELETE FROM {table} WHERE {column}=?',(sid,))
        return str(backup)

    def finish_tracking_deletion(self,symbol):
        with self.connect() as db:db.execute("UPDATE tracking_deletion_intents SET status='DELETED' WHERE symbol=?",(symbol,))

    def save_preferences(self,symbol,value):
        with self.connect() as db:
            db.execute('INSERT INTO live_preferences VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload',
                       (symbol.lower(),canonical(value)))

    def ingest(self,facts,stamp):
        time_key=lambda value:str(value or '').split('T')[-1][:8]
        session=facts['session'];identity=session['tracking_session_id']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM live_expired_sessions WHERE session_id=?',(identity,)).fetchone():
                return {'listener_event_cursor':session.get('source_event_max',0),'listener_observation_cursor':session.get('source_observation_max'),'session':session,'expired':True,'errors':[{'code':'RETENTION_EXPIRED'}]}
            if db.execute('SELECT 1 FROM live_retired_sessions WHERE session_id=?',(identity,)).fetchone():
                return {'listener_event_cursor':0,'listener_observation_cursor':None,'session':session,'errors':[{'code':'TRACKING_DELETED'}]}
            mutations=[]
            for kind,rows in (('EVENT',facts['events']),('OBSERVATION',facts['observations'])):
                for row in rows:
                    key=str(row['event_seq']) if kind=='EVENT' else row.get('record_id') or (row.get('source_format','OBSERVATION')+':'+time_key(row.get('timestamp') or row.get('requested_time') or row.get('last_observation_time')))
                    if not key:continue
                    if kind=='EVENT' and session.get('native_event_stream'):
                        existing=db.execute('SELECT payload FROM live_ingested_facts WHERE session_id=? AND kind=? AND identity=?',(identity,kind,key)).fetchone()
                        if existing and existing[0]!=canonical(row):mutations.append({'code':'SOURCE_EVENT_MUTATED','event_seq':row['event_seq']})
                    db.execute('INSERT OR IGNORE INTO live_ingested_facts VALUES(?,?,?,?,?)',(identity,kind,key,canonical(row),stamp))
            previous=db.execute('SELECT payload FROM live_ingestion WHERE session_id=?',(identity,)).fetchone()
            before=json.loads(previous[0]) if previous else {}
            errors=[e for e in session.get('source_errors',[]) if e.get('code')!='INCOMPLETE_TAIL']+mutations
            event_cursor=before.get('listener_event_cursor',0)
            if session.get('native_event_stream') and session.get('source_event_max',0)<event_cursor:
                errors.append({'code':'SOURCE_EVENT_TRUNCATED','previous':event_cursor,'source_max':session.get('source_event_max',0)})
            for seq in sorted({r['event_seq'] for r in facts['events'] if r['event_seq']>event_cursor}):
                if session.get('native_event_stream') and seq!=event_cursor+1:
                    errors.append({'code':'SOURCE_EVENT_GAP','expected':event_cursor+1,'found':seq});break
                event_cursor=seq
            if session.get('native_export'):
                backfill_time=max((r.get('interval_end') or '' for r in facts['observations'] if r.get('delivery') in ('BACKFILL','RECOVERED')),default='')
                db.execute('INSERT OR IGNORE INTO native_control VALUES(?,?,?)',
                    (identity,'BACKFILL_BASELINE',canonical({'event_seq':session.get('source_event_max',0),'observation_time':backfill_time,'created_at':stamp})))
                baseline=json.loads(db.execute('SELECT payload FROM native_control WHERE session_id=? AND kind=?',(identity,'BACKFILL_BASELINE')).fetchone()[0])
                if backfill_time>baseline.get('observation_time',''):
                    baseline.update(observation_time=backfill_time,event_seq=max(baseline['event_seq'],session.get('source_event_max',0)))
                    db.execute('UPDATE native_control SET payload=? WHERE session_id=? AND kind=?',(canonical(baseline),identity,'BACKFILL_BASELINE'))
            value={'listener_event_cursor':event_cursor,
                   'listener_observation_cursor':max([x for x in (before.get('listener_observation_cursor'),session.get('source_observation_max')) if x],key=time_key,default=None),
                   'read_at':stamp,'session':session,'source_watermark':session.get('source_watermark')}
            value['errors']=errors
            if errors:
                value['listener_observation_cursor']=before.get('listener_observation_cursor')
                value['source_watermark']=before.get('source_watermark')
            db.execute('INSERT INTO live_ingestion VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET payload=excluded.payload',(identity,canonical(value)))
        return value

    def native_control(self,identity,kind):
        with self.connect(True) as db:
            row=db.execute('SELECT payload FROM native_control WHERE session_id=? AND kind=?',(identity,kind)).fetchone()
        return json.loads(row[0]) if row else None

    def enqueue_request(self,request_id,frozen,settings,force):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM live_retired_sessions WHERE session_id=?',(frozen['tracking_session_id'],)).fetchone():
                from contracts.live.bridge import BridgeError
                raise BridgeError('TRACKING_DELETED')
            count=db.execute("SELECT count(*) FROM live_analysis_requests WHERE symbol=? AND status IN ('QUEUED','RUNNING')",(frozen['symbol'],)).fetchone()[0]
            if count>=32:
                from contracts.live.bridge import BridgeError
                raise BridgeError('ADVISORY_QUEUE_FULL','该股票排队已满，请等待当前分析。',409)
            payload={'frozen':frozen,'settings':settings,'force':force}
            row=db.execute('INSERT INTO live_analysis_requests(request_id,symbol,session_id,status,payload) VALUES(?,?,?,?,?)',
                (request_id,frozen['symbol'],frozen['tracking_session_id'],'QUEUED',canonical(payload)))
            return row.lastrowid

    def request_status(self,request_id,status,payload=None):
        with self.connect() as db:
            if payload is None:db.execute('UPDATE live_analysis_requests SET status=? WHERE request_id=?',(status,request_id))
            else:db.execute('UPDATE live_analysis_requests SET status=?,payload=? WHERE request_id=?',(status,canonical(payload),request_id))

    def matching_request(self,symbol,window_key):
        with self.connect(True) as db:
            rows=db.execute("SELECT * FROM live_analysis_requests WHERE symbol=? AND status IN ('QUEUED','RUNNING') ORDER BY sequence",(symbol,)).fetchall()
        for row in rows:
            value=json.loads(row['payload'])
            if value.get('task',{}).get('window_key')==window_key:
                return {**dict(row),'payload':value}

    def annotate_request(self,request_id,**metadata):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM live_analysis_requests WHERE request_id=?',(request_id,)).fetchone()
            if not row:return
            payload=json.loads(row[0]);payload['task']={**payload.get('task',{}),**metadata}
            db.execute('UPDATE live_analysis_requests SET payload=? WHERE request_id=?',(canonical(payload),request_id))

    def record_input_failure(self,request_id,symbol,identity,metadata):
        with self.connect() as db:
            db.execute("INSERT INTO live_analysis_requests(request_id,symbol,session_id,status,payload) VALUES(?,?,?,'FAILED',?)",
                       (request_id,symbol,identity,canonical({'task':metadata})))

    def latest_request(self,identity):
        with self.connect(True) as db:
            row=db.execute(self._task_projection+' WHERE session_id=? ORDER BY sequence DESC LIMIT 1',(identity,)).fetchone()
        return {**dict(row),'payload':json.loads(row['payload'])} if row else None

    def active_request(self,identity):
        with self.connect(True) as db:
            row=db.execute(self._task_projection+" WHERE session_id=? AND status IN ('RUNNING','QUEUED') ORDER BY CASE status WHEN 'RUNNING' THEN 0 ELSE 1 END,sequence LIMIT 1",(identity,)).fetchone()
        return {**dict(row),'payload':json.loads(row['payload'])} if row else None

    # Polling reads task metadata, never materializes its full frozen evidence.
    _task_projection='''SELECT request_id,status,sequence,json_object(
        'task',json(coalesce(json_extract(payload,'$.task'),'{}')),'frozen',json_object(
        'trigger_type',json_extract(payload,'$.frozen.trigger_type'),
        'requested_at',json_extract(payload,'$.frozen.requested_at'),
        'created_at',json_extract(payload,'$.frozen.created_at'),
        'data_through_at',json_extract(payload,'$.frozen.data_through_at'))) AS payload FROM live_analysis_requests'''

    def commit_success(self,frozen,opinion):
        """Advance all success markers atomically, only after immutable Opinion exists."""
        identity=frozen['tracking_session_id']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO advisory_provenance_audit VALUES(?,?)',
                       (opinion['request_id'],canonical(frozen.get('previous_eligibility',{}))))
            if not opinion.get('effective_result',True) or db.execute('SELECT 1 FROM live_retired_sessions WHERE session_id=?',(identity,)).fetchone():return
            for kind,values in (('ADVISED_TRIGGERS',{r['trigger_id'] for r in frozen.get('live_triggers',[])}),
                                ('ADVISED_RECORDS',{r['record_id'] for r in frozen['incremental_evidence']['observations'] if r.get('record_id')})):
                row=db.execute('SELECT payload FROM native_control WHERE session_id=? AND kind=?',(identity,kind)).fetchone()
                merged=sorted(set(json.loads(row[0]) if row else [])|values)
                db.execute('INSERT INTO native_control VALUES(?,?,?) ON CONFLICT(session_id,kind) DO UPDATE SET payload=excluded.payload',(identity,kind,canonical(merged)))
            db.execute("INSERT INTO native_control VALUES(?,'EVALUATION_CONTEXT',?) ON CONFLICT(session_id,kind) DO UPDATE SET payload=excluded.payload",(identity,canonical(frozen['evaluation_context_hash'])))
            db.execute('''INSERT INTO advisory_cursors VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tracking_session_id)
                DO UPDATE SET symbol=excluded.symbol,session_date=excluded.session_date,
                last_advised_event_seq=excluded.last_advised_event_seq,last_advised_observation_time=excluded.last_advised_observation_time,
                last_advisory_id=excluded.last_advisory_id,last_input_hash=excluded.last_input_hash,updated_at=excluded.updated_at''',
                (identity,frozen['symbol'],frozen['session_date'],frozen['data_through_event_seq'],frozen.get('data_through_observation_time'),opinion['advisory_id'],frozen['data_hash'],opinion['generated_at']))
            db.execute('DELETE FROM advisory_pending WHERE tracking_session_id=?',(identity,))

    def queued_request(self,symbol):
        with self.connect(True) as db:
            row=db.execute("SELECT * FROM live_analysis_requests WHERE symbol=? AND status='QUEUED' ORDER BY sequence LIMIT 1",(symbol,)).fetchone()
        return {**dict(row),'payload':json.loads(row['payload'])} if row else None

    def queued_count(self,identity):
        with self.connect(True) as db:
            return db.execute("SELECT count(*) FROM live_analysis_requests WHERE session_id=? AND status='QUEUED'",(identity,)).fetchone()[0]

    def request_superseded(self,symbol,sequence):
        with self.connect(True) as db:
            return db.execute("SELECT 1 FROM live_analysis_requests WHERE symbol=? AND sequence>? AND status IN ('QUEUED','RUNNING','COMPLETED') LIMIT 1",(symbol,sequence)).fetchone() is not None

    def mark_read(self,identity,opinion_position,event_seq):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT payload FROM native_control WHERE session_id=? AND kind='READ_POSITION'",(identity,)).fetchone()
            old=json.loads(row[0]) if row else {}
            value={'opinion_position':max(old.get('opinion_position',0),opinion_position),
                   'event_seq':max(old.get('event_seq',0),event_seq)}
            db.execute("INSERT INTO native_control VALUES(?,'READ_POSITION',?) ON CONFLICT(session_id,kind) DO UPDATE SET payload=excluded.payload",(identity,canonical(value)))
        return value

    def save_native_control(self,identity,kind,value):
        with self.connect() as db:db.execute('INSERT INTO native_control VALUES(?,?,?) ON CONFLICT(session_id,kind) DO UPDATE SET payload=excluded.payload',(identity,kind,canonical(value)))

    def record_provenance(self,request_id,value):
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO advisory_provenance_audit VALUES(?,?)',(request_id,canonical(value)))

    def ingestion(self,identity):
        with self.connect(True) as db:row=db.execute('SELECT payload FROM live_ingestion WHERE session_id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else {}

    def ingested_facts(self,identity,kind):
        with self.connect(True) as db:rows=db.execute('SELECT payload FROM live_ingested_facts WHERE session_id=? AND kind=? ORDER BY rowid',(identity,kind)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def ingested_at(self,identity,record_id):
        with self.connect(True) as db:
            row=db.execute("SELECT read_at FROM live_ingested_facts WHERE session_id=? AND kind='OBSERVATION' AND identity=?",(identity,record_id)).fetchone()
        return row[0] if row else None

    def save_cursor(self,value):
        with self.connect() as db:
            db.execute('''INSERT INTO advisory_cursors VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tracking_session_id)
                DO UPDATE SET symbol=excluded.symbol,session_date=excluded.session_date,
                last_advised_event_seq=excluded.last_advised_event_seq,
                last_advised_observation_time=excluded.last_advised_observation_time,
                last_advisory_id=excluded.last_advisory_id,last_input_hash=excluded.last_input_hash,updated_at=excluded.updated_at''',
                tuple(value[k] for k in ('tracking_session_id','symbol','session_date','last_advised_event_seq',
                      'last_advised_observation_time','last_advisory_id','last_input_hash','updated_at')))

    def pending(self,identity):
        with self.connect(True) as db:row=db.execute('SELECT * FROM advisory_pending WHERE tracking_session_id=?',(identity,)).fetchone()
        return dict(row) if row else None

    def save_pending(self,value):
        with self.connect() as db:
            db.execute('''INSERT INTO advisory_pending VALUES(?,?,?,?,?) ON CONFLICT(tracking_session_id)
                DO UPDATE SET event_seq=excluded.event_seq,observation_time=excluded.observation_time,input_hash=excluded.input_hash''',
                tuple(value[k] for k in ('tracking_session_id','first_seen_at','event_seq','observation_time','input_hash')))

    def clear_pending(self,identity):
        with self.connect() as db:db.execute('DELETE FROM advisory_pending WHERE tracking_session_id=?',(identity,))

    def begin_request(self,identity,symbol,request_id,stamp):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT state FROM advisory_coordinator WHERE lower(symbol)=lower(?) AND state='RUNNING'",(symbol,)).fetchone()
            if row and row['state']=='RUNNING':
                db.execute('UPDATE advisory_coordinator SET pending=1,updated_at=? WHERE tracking_session_id=?',(stamp,identity));return False
            db.execute('''INSERT INTO advisory_coordinator VALUES(?,?,?,?,?,?) ON CONFLICT(tracking_session_id)
                DO UPDATE SET symbol=excluded.symbol,state='RUNNING',active_request_id=excluded.active_request_id,pending=0,updated_at=excluded.updated_at''',
                (identity,symbol,'RUNNING',request_id,0,stamp));return True

    def finish_request(self,identity,stamp):
        with self.connect() as db:
            row=db.execute('SELECT pending FROM advisory_coordinator WHERE tracking_session_id=?',(identity,)).fetchone()
            pending=bool(row and row['pending'])
            db.execute("UPDATE advisory_coordinator SET state='IDLE',active_request_id=NULL,pending=0,updated_at=? WHERE tracking_session_id=?",(stamp,identity))
            return pending

    def has_running_work(self):
        with self.connect(True) as db:
            return bool(db.execute("SELECT 1 FROM advisory_coordinator WHERE state='RUNNING' OR pending>0 LIMIT 1").fetchone())

    def active_requests(self):
        with self.connect(True) as db:
            return bool(db.execute("SELECT 1 FROM live_analysis_requests WHERE status IN ('RUNNING','QUEUED') LIMIT 1").fetchone())

    def coordinator(self,identity):
        with self.connect(True) as db:row=db.execute('SELECT * FROM advisory_coordinator WHERE tracking_session_id=?',(identity,)).fetchone()
        return dict(row) if row else {'tracking_session_id':identity,'state':'IDLE','pending':0}

    def record_portfolio_outcome(self, advisory_id, value, stamp):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO portfolio_outcomes VALUES(?,?,?)',(advisory_id,canonical(value),stamp))

    def portfolio_outcome(self, advisory_id):
        with self.connect(True) as db:
            row=db.execute('SELECT payload FROM portfolio_outcomes WHERE advisory_id=?',(advisory_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def record_failure(self,value):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO advisory_failures(request_id,tracking_session_id,symbol,error_code,detail,failed_at,source_hash) VALUES(?,?,?,?,?,?,?)',tuple(value.get(k) for k in
                ('request_id','tracking_session_id','symbol','error_code','detail','failed_at','source_hash')))

    def latest_failure(self,identity):
        with self.connect(True) as db:row=db.execute('SELECT * FROM advisory_failures WHERE tracking_session_id=? ORDER BY failed_at DESC LIMIT 1',(identity,)).fetchone()
        return dict(row) if row else None


class AdvisoryOpinionRepository:
    def __init__(self,store):
        self.store=store;store.ensure()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS retention_tombstones(advisory_id TEXT PRIMARY KEY,input_id TEXT,session_date TEXT,cleaned_at TEXT)')
            db.executescript('''CREATE TABLE IF NOT EXISTS advisory_inputs(
                input_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL UNIQUE,payload TEXT NOT NULL CHECK(json_valid(payload)),created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS advisory_opinions(
                advisory_id TEXT PRIMARY KEY,input_id TEXT NOT NULL UNIQUE REFERENCES advisory_inputs(input_id),
                symbol TEXT NOT NULL,tracking_session_id TEXT NOT NULL,session_date TEXT NOT NULL,
                generated_at TEXT NOT NULL,payload TEXT NOT NULL CHECK(json_valid(payload)));
                CREATE INDEX IF NOT EXISTS advisory_opinions_symbol_time ON advisory_opinions(symbol,generated_at DESC);
                CREATE TRIGGER IF NOT EXISTS advisory_inputs_no_update BEFORE UPDATE ON advisory_inputs BEGIN SELECT RAISE(ABORT,'Advisory input is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS advisory_inputs_no_delete BEFORE DELETE ON advisory_inputs BEGIN SELECT RAISE(ABORT,'Advisory input is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS advisory_opinions_no_update BEFORE UPDATE ON advisory_opinions BEGIN SELECT RAISE(ABORT,'Advisory opinion is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS advisory_opinions_no_delete BEFORE DELETE ON advisory_opinions BEGIN SELECT RAISE(ABORT,'Advisory opinion is immutable'); END;''')

    @contextmanager
    def connect(self,readonly=False):
        path=self.store.path('advisory.db')
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) if readonly else sqlite3.connect(path,timeout=5)
        try:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
            if readonly:db.execute('PRAGMA query_only=ON')
            with db:yield db
        finally:db.close()

    def append(self,frozen_input,opinion):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM retention_tombstones WHERE advisory_id=? OR input_id=?',(opinion['advisory_id'],frozen_input['input_id'])).fetchone():raise ValueError('RETENTION_EXPIRED_ID_REUSE')
            db.execute('INSERT INTO advisory_inputs VALUES(?,?,?,?)',(frozen_input['input_id'],frozen_input['input_hash'],canonical(frozen_input),frozen_input['created_at']))
            db.execute('INSERT INTO advisory_opinions VALUES(?,?,?,?,?,?,?)',(opinion['advisory_id'],frozen_input['input_id'],opinion['symbol'],
                opinion['tracking_session_id'],opinion['session_date'],opinion['generated_at'],canonical(opinion)))

    def latest(self,symbol,identity=None):
        with self.connect(True) as db:
            rows=db.execute('SELECT rowid,payload FROM advisory_opinions WHERE lower(symbol)=lower(?) AND (? IS NULL OR tracking_session_id=?)',(symbol,identity,identity)).fetchall()
        values=[(json.loads(row['payload']),row['rowid']) for row in rows]
        values=[(v,p) for v,p in values if v.get('effective_result',True)]
        return max(values,key=lambda pair:(self.effective_key(pair[0]),pair[1]))[0] if values else None

    def tracking_references(self,symbol):
        with self.connect(True) as db:return [dict(r) for r in db.execute('SELECT advisory_id,tracking_session_id FROM advisory_opinions WHERE symbol=?',(symbol,))]

    @staticmethod
    def effective_key(value):
        from engines.live.native_health import instant
        at=value.get('data_through_at') or value.get('data_through_time')
        try:stamp=instant(at,value.get('session_date')).timestamp() if at else 0
        except (ValueError,TypeError):stamp=0
        return stamp,value.get('data_through_event_seq',0),value.get('request_sequence',0)

    def reading(self,symbol,identity,after=0):
        with self.connect(True) as db:
            rows=db.execute('SELECT rowid,payload FROM advisory_opinions WHERE symbol=? AND tracking_session_id=? AND rowid>? ORDER BY rowid',(symbol,identity,after)).fetchall()
        return [{'position':row['rowid'],'opinion':json.loads(row['payload'])} for row in rows]

    def opinion_position(self,advisory_id,identity):
        with self.connect(True) as db:
            row=db.execute('SELECT rowid FROM advisory_opinions WHERE advisory_id=? AND tracking_session_id=?',(advisory_id,identity)).fetchone()
        return row[0] if row else None

    def by_id(self,identity):
        with self.connect(True) as db:row=db.execute('SELECT payload FROM advisory_opinions WHERE advisory_id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def expired_opinion(self,identity):
        with self.connect(True) as db:return db.execute('SELECT 1 FROM retention_tombstones WHERE advisory_id=?',(identity,)).fetchone() is not None

    def input(self,input_id):
        with self.connect(True) as db:row=db.execute('SELECT payload FROM advisory_inputs WHERE input_id=?',(input_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def latest_bundle(self,symbol,identity=None):
        opinion=self.latest(symbol,identity)
        return (opinion,self.input(opinion['input_id'])) if opinion else (None,None)

    def history(self,symbol,limit=50,identity=None):
        with self.connect(True) as db:
            rows=db.execute('SELECT payload FROM advisory_opinions WHERE lower(symbol)=lower(?) AND (? IS NULL OR tracking_session_id=?) ORDER BY generated_at DESC,rowid DESC LIMIT ?',
                            (symbol,identity,identity,max(1,min(int(limit),200)))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def history_page(self,symbol,identity,limit=10,before=None,anchor=None):
        """Stable rowid snapshot; one page retained by the reader, no offset drift."""
        limit=max(1,min(int(limit),20))
        with self.connect(True) as db:
            if anchor is None:anchor=db.execute('SELECT coalesce(max(rowid),0) FROM advisory_opinions').fetchone()[0]
            anchor=max(0,int(anchor));before=int(before) if before is not None else anchor+1
            rows=db.execute('SELECT rowid,payload FROM advisory_opinions WHERE symbol=? AND tracking_session_id=? AND rowid<=? AND rowid<? ORDER BY rowid DESC LIMIT ?',
                            (symbol,identity,anchor,before,limit+1)).fetchall()
        return {'opinions':[json.loads(r['payload']) for r in rows[:limit]],'anchor':anchor,
                'next_before':rows[limit-1]['rowid'] if len(rows)>limit else None}

    def timeline(self,symbol,limit=100):
        with self.connect(True) as db:
            rows=db.execute('''SELECT payload FROM (SELECT rowid,payload FROM advisory_opinions
                WHERE lower(symbol)=lower(?) ORDER BY generated_at DESC,rowid DESC LIMIT ?)
                ORDER BY rowid ASC''',(symbol,max(1,min(int(limit),200)))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def count(self):
        with self.connect(True) as db:return db.execute('SELECT count(*) FROM advisory_opinions').fetchone()[0]
