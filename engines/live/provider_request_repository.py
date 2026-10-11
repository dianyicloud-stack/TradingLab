"""Live-owned append-only provider evidence, supplied by explicit capability."""
from pathlib import Path
import json
import sqlite3
from contextlib import closing
import uuid
from datetime import datetime,timezone

def expire_inputs(path,input_ids):
    """Owner-only expiry of evidence whose input has a committed expiry marker."""
    if not Path(path).exists() or not input_ids:return
    with closing(sqlite3.connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='records_no_delete'").fetchone()
        if trigger:db.execute('DROP TRIGGER records_no_delete')
        db.executemany('DELETE FROM records WHERE input_id=?',[(s,) for s in input_ids])
        if trigger:db.execute(trigger[0])


class ProviderRequestRepository:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'provider_requests.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''CREATE TABLE IF NOT EXISTS records(
                id TEXT PRIMARY KEY, input_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'IMMUTABLE_REQUEST');END;
                CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'IMMUTABLE_REQUEST');END;''')

    def append(self,input_id,kind,value):
        identity=uuid.uuid4().hex
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO records VALUES(?,?,?,?,?)',(identity,input_id,kind,datetime.now(timezone.utc).isoformat(),json.dumps(value,ensure_ascii=False,allow_nan=False)))
        return identity
