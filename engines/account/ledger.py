"""Account-owned, physically partitioned append-only ledger with transactional projections."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from uuid import uuid4
from contracts.account.portfolio import AccountError, ACCOUNT_TYPES


def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def stamp(): return datetime.now(timezone.utc).isoformat()
def identity(prefix): return prefix+'-'+uuid4().hex


class AccountRepository:
    def __init__(self, store): self.store = store

    def path(self, account_id):
        if not re.fullmatch(r'AC-[a-f0-9]{32}',account_id): raise AccountError('INVALID_ACCOUNT_ID',status=400)
        return self.store.path(account_id+'/account.db')

    @contextmanager
    def transaction(self, account_id, *, create=False):
        control=getattr(self,'control',None)
        with control.gate() if control else nullcontext():
            with self._transaction(account_id,create=create) as db:yield db

    @contextmanager
    def _transaction(self, account_id, *, create=False):
        path=self.path(account_id)
        if getattr(self,'control',None) and self.control.deleted(account_id):raise AccountError('ACCOUNT_DELETED')
        if not create and not path.is_file(): raise AccountError('ACCOUNT_NOT_FOUND',status=404)
        if create: path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(path,timeout=30)
        db.row_factory=sqlite3.Row
        try:
            if create:
                db.executescript('''
                CREATE TABLE IF NOT EXISTS ledger(seq INTEGER PRIMARY KEY, ledger_event_id TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projection(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LEDGER'); END;
                CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LEDGER'); END;
                CREATE TRIGGER IF NOT EXISTS ledger_no_replace BEFORE INSERT ON ledger WHEN EXISTS(SELECT 1 FROM ledger WHERE seq=NEW.seq OR ledger_event_id=NEW.ledger_event_id) BEGIN SELECT RAISE(ABORT,'IMMUTABLE_LEDGER'); END;
                ''')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally: db.close()

    def events(self, db):
        result=[]; previous='0'*64
        for row in db.execute('SELECT * FROM ledger ORDER BY seq'):
            value=json.loads(row['payload'])
            if row['previous_hash']!=previous or row['event_hash']!=digest([row['seq'],row['event_type'],value,previous]):
                raise AccountError('LEDGER_HASH_MISMATCH')
            result.append(value); previous=row['event_hash']
        return result

    def append(self, db, event_type, payload):
        row=db.execute('SELECT seq,event_hash FROM ledger ORDER BY seq DESC LIMIT 1').fetchone()
        seq, previous=(row['seq']+1,row['event_hash']) if row else (1,'0'*64)
        event={'ledger_event_id':identity('LE'), 'event_type':event_type, 'created_at':stamp(), 'immutable':True, **deepcopy(payload)}
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?)',(seq,event['ledger_event_id'],event_type,canonical(event),previous,digest([seq,event_type,event,previous])))
        return event

    def projection(self, db):
        row=db.execute('SELECT body FROM projection WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def save_projection(self, db, value):
        db.execute('INSERT INTO projection VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(canonical(value),))

    def list(self):
        if not self.store.path().exists(): return []
        result=[]
        for path in sorted(self.store.path().glob('AC-*/account.db')):
            if getattr(self,'control',None) and self.control.deleted(path.parent.name):continue
            with self.transaction(path.parent.name) as db:
                events=self.events(db)
                if events:
                    meta=events[0]['account']; result.append(meta)
        return result

    def create(self, account_type, capital, policy, *, context_id=None, generation=1, parent=None, namespace='USER', account_id=None):
        if account_type not in ACCOUNT_TYPES: raise AccountError('INVALID_ACCOUNT_TYPE')
        if account_type!='LIVE_SHADOW' and not context_id: raise AccountError('CONTEXT_REQUIRED')
        account_id=account_id or identity('AC')
        with self.transaction(account_id,create=True) as db:
            if self.events(db): raise AccountError('ACCOUNT_EXISTS')
            meta={'account_id':account_id,'account_type':account_type,'account_generation':generation,'parent_account_id':parent,
                  'context_id':context_id,'namespace':namespace,'status':'ACTIVE','initial_capital':capital,'created_at':stamp()}
            self.append(db,'ACCOUNT_CREATED',{'account':meta,'policy':policy,'account_id':account_id})
        return meta
