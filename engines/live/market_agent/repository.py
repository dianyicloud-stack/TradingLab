"""Agent-owned immutable journals + transactional restart/read projections."""
from pathlib import Path
import hashlib,json,sqlite3
from datetime import datetime,timezone
from contextlib import contextmanager
from contracts.live.market_agent import AgentError

def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(encode(value).encode()).hexdigest()

class AgentRepository:
    def __init__(self,root,clock=None):
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.path=Path(root)/'market_agent.db';self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,state TEXT NOT NULL);
              INSERT OR IGNORE INTO checkpoint VALUES(1,0,'{}');
              CREATE TABLE IF NOT EXISTS command_version(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);
              INSERT OR IGNORE INTO command_version VALUES(1,0);
              CREATE TABLE IF NOT EXISTS commands(command_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS facts(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,identity TEXT NOT NULL,revision INTEGER NOT NULL,sha256 TEXT NOT NULL,payload TEXT NOT NULL,recorded_at TEXT NOT NULL,UNIQUE(kind,identity,revision));
              CREATE INDEX IF NOT EXISTS fact_identity ON facts(kind,identity,seq);
              CREATE TABLE IF NOT EXISTS retired_tracking_sessions(session_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,command_id TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS expired_fact_sessions(session_id TEXT PRIMARY KEY,keep_day TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS retention_readiness(id INTEGER PRIMARY KEY CHECK(id=1),day TEXT NOT NULL,payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS retention_validation(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS retention_identity(id INTEGER PRIMARY KEY CHECK(id=1),identity TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS protected_tracking_facts(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS protected_tracking_no_delete BEFORE DELETE ON protected_tracking_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ARCHIVE');END;
              CREATE TRIGGER IF NOT EXISTS protected_tracking_no_update BEFORE UPDATE ON protected_tracking_facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_ARCHIVE');END;
              CREATE TRIGGER IF NOT EXISTS facts_no_update BEFORE UPDATE ON facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_MARKET_FACT');END;
              CREATE TRIGGER IF NOT EXISTS facts_no_delete BEFORE DELETE ON facts BEGIN SELECT RAISE(ABORT,'IMMUTABLE_MARKET_FACT');END;
              CREATE TRIGGER IF NOT EXISTS commands_no_update BEFORE UPDATE ON commands BEGIN SELECT RAISE(ABORT,'IMMUTABLE_COMMAND');END;
              CREATE TRIGGER IF NOT EXISTS commands_no_delete BEFORE DELETE ON commands BEGIN SELECT RAISE(ABORT,'IMMUTABLE_COMMAND');END;
            ''')
            import uuid
            db.execute('INSERT OR IGNORE INTO retention_identity VALUES(1,?)',(str(uuid.uuid4()),))
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()
    def checkpoint(self):
        with self.connect() as db:v,s=db.execute('SELECT version,state FROM checkpoint WHERE id=1').fetchone()
        return v,json.loads(s)
    def replay(self,command):
        with self.connect() as db:row=db.execute('SELECT fingerprint,result FROM commands WHERE command_id=?',(command['command_id'],)).fetchone()
        if not row:return None
        if row[0]!=digest(command):raise AgentError('COMMAND_ID_CONFLICT')
        return json.loads(row[1])
    def command_version(self):
        with self.connect() as db:return db.execute('SELECT version FROM command_version WHERE id=1').fetchone()[0]
    def commit(self,state,records,*,command=None,expected=None,result_data=None):
        now=self.clock().isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');version=db.execute('SELECT version FROM checkpoint WHERE id=1').fetchone()[0]
            command_version=db.execute('SELECT version FROM command_version WHERE id=1').fetchone()[0]
            if expected is not None and expected!=command_version:raise AgentError('VERSION_CONFLICT')
            retired={r[0] for r in db.execute('SELECT session_id FROM retired_tracking_sessions')}
            expired={r[0] for r in db.execute('SELECT session_id FROM expired_fact_sessions')}
            if expired:
                from .retention import prune
                state=prune(state,expired)
            if retired:
                from .tracking_delete import scrub
                state=scrub(state,retired)
            for kind,identity,payload in records:
                if (payload.get('tracking_session_id') or payload.get('session')) in expired and kind not in ('HANDOFF','ACK_RECEIPT'):continue
                if payload.get('tracking_session_id') in retired and kind not in ('HANDOFF','ACK_RECEIPT'):continue
                sha=digest(payload);old=db.execute('SELECT revision,sha256 FROM facts WHERE kind=? AND identity=? ORDER BY seq DESC LIMIT 1',(kind,identity)).fetchone()
                if old and old[1]==sha:continue
                revision=(old[0]+1) if old else 1
                if kind in ('EVENT','HANDOFF','ACK_RECEIPT') and old:raise AgentError('IMMUTABLE_SOURCE_ID_MUTATED')
                db.execute('INSERT INTO facts(kind,identity,revision,sha256,payload,recorded_at) VALUES(?,?,?,?,?,?)',(kind,identity,revision,sha,encode(payload),now))
            version+=1;db.execute('UPDATE checkpoint SET version=?,state=? WHERE id=1',(version,encode(state)))
            if command:command_version+=1;db.execute('UPDATE command_version SET version=? WHERE id=1',(command_version,))
            result={'schema_version':'1.0','version':command_version,'fact_version':version,'status':'COMMITTED',**(result_data or {})}
            if command:db.execute('INSERT INTO commands VALUES(?,?,?)',(command['command_id'],digest(command),encode(result)))
        return result
    def facts(self,kind=None):
        with self.connect() as db:
            rows=db.execute('SELECT seq,kind,identity,revision,sha256,payload,recorded_at FROM facts'+(' WHERE kind=?' if kind else '')+' ORDER BY seq',(kind,) if kind else ()).fetchall()
        return [dict(seq=s,kind=k,identity=i,revision=r,sha256=h,payload=json.loads(p),recorded_at=t) for s,k,i,r,h,p,t in rows]
