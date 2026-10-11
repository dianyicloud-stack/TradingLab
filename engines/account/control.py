"""Account-owned metadata and durable execution binding; never copies a ledger."""
from contextlib import contextmanager, closing
import json
import sqlite3
from threading import RLock, local
from contracts.account.portfolio import AccountError
from engines.account.ledger import canonical, digest, identity


class AccountControl:
    def __init__(self, repository, namespace):
        self.repository, self.namespace = repository, namespace
        self.path = repository.store.path('portfolio-control.db')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock, self.local = RLock(), local()
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, namespace TEXT NOT NULL,
                name TEXT NOT NULL, origin TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS binding(namespace TEXT PRIMARY KEY, account_id TEXT, version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS creations(namespace TEXT, request_key TEXT, hash TEXT, account_id TEXT,
                PRIMARY KEY(namespace,request_key));
            ''')
        # Explicit startup migration. Only one unambiguous pre-existing Live account
        # may retain the old implicit binding; no GET performs this migration.
        with self.gate() as db:
            if not db.execute('SELECT 1 FROM binding WHERE namespace=?',(namespace,)).fetchone():
                rows=[r for r in repository.list() if r['namespace']==namespace]
                for row in rows:
                    live=row['account_type']=='LIVE_SHADOW'
                    db.execute('INSERT OR IGNORE INTO accounts VALUES(?,?,?,?,?,?)',
                        (row['account_id'],namespace,'原实时账户' if live else '退役账户',
                         'MIGRATED_LIVE' if live else 'RETIRED', 'ACTIVE' if live else 'QUARANTINED',canonical(row)))
                live=[r for r in rows if r['account_type']=='LIVE_SHADOW' and r['status']=='ACTIVE']
                db.execute('INSERT INTO binding VALUES(?,?,?)',(namespace,live[0]['account_id'] if len(live)==1 else None,1))

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        try:yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    @contextmanager
    def gate(self):
        """Cross-instance fence for binding, deletion and final execution (not AI)."""
        with self.lock:
            if getattr(self.local,'db',None) is not None:
                yield self.local.db;return
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE');self.local.db=db
                try:yield db
                finally:self.local.db=None

    def rows(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM accounts WHERE namespace=?',(self.namespace,))]

    def binding(self):
        with self.connect() as db:
            return dict(db.execute('SELECT account_id,version AS binding_version FROM binding WHERE namespace=?',(self.namespace,)).fetchone())

    def bind(self, account_id, version):
        if account_id is not None:
            if not isinstance(account_id,str):raise AccountError('INVALID_ACCOUNT_ID',status=400)
            self.repository.path(account_id)
        with self.gate() as db:
            row=db.execute('SELECT * FROM binding WHERE namespace=?',(self.namespace,)).fetchone()
            if type(version) is not int or row['version']!=version:raise AccountError('BINDING_VERSION_CHANGED')
            if account_id is not None:
                valid=db.execute("SELECT 1 FROM accounts WHERE id=? AND namespace=? AND status='ACTIVE'",(account_id,self.namespace)).fetchone()
                if not valid:raise AccountError('ACCOUNT_NOT_FOUND',status=404)
            db.execute('UPDATE binding SET account_id=?,version=version+1 WHERE namespace=?',(account_id,self.namespace))
            return {'account_id':account_id,'binding_version':version+1}

    @staticmethod
    def name(value):
        if not isinstance(value,str) or not 1<=len(value.strip())<=60 or any(ord(c)<32 for c in value):
            raise AccountError('INVALID_ACCOUNT_NAME',status=400)
        return value.strip()

    def rename(self, account_id, name):
        with self.gate() as db:
            db.execute("UPDATE accounts SET name=? WHERE id=? AND namespace=? AND status='ACTIVE'",(self.name(name),account_id,self.namespace))

    def deleted(self, account_id):
        with self.connect() as db:
            row=db.execute('SELECT status FROM accounts WHERE id=?',(account_id,)).fetchone()
            return bool(row and row[0] in ('DELETING','DELETED'))

    def delete(self, account_id):
        # Commit the tombstone and unbinding BEFORE physical work. Retrying after
        # an interruption completes the same deletion; the old ID cannot revive.
        with self.gate() as db:
            row=db.execute('SELECT * FROM accounts WHERE id=? AND namespace=?',(account_id,self.namespace)).fetchone()
            if not row:raise AccountError('ACCOUNT_NOT_FOUND',status=404)
            if row['status']=='QUARANTINED':raise AccountError('ACCOUNT_READ_ONLY')
            db.execute("UPDATE accounts SET status='DELETING',name='',metadata='{}' WHERE id=?",(account_id,))
            db.execute('UPDATE binding SET account_id=NULL,version=version+1 WHERE namespace=? AND account_id=?',(self.namespace,account_id))
        with self.gate() as db:
            root=self.repository.store.path().resolve();folder=self.repository.path(account_id).parent
            if folder.exists():
                if folder.is_symlink() or folder.is_junction() or folder.resolve().parent!=root:raise AccountError('UNSAFE_ACCOUNT_PATH')
                files=list(folder.iterdir())
                if any(p.is_symlink() or not p.is_file() or p.name not in ('account.db','account.db-wal','account.db-shm','retained-context.json') for p in files):
                    raise AccountError('UNKNOWN_ACCOUNT_FILES')
                # All Account writers share the fence; close/check SQLite before
                # unlinking its owned files. Never touch any other Owner's data.
                database=folder/'account.db'
                if database.exists():
                    with closing(sqlite3.connect(database,timeout=1)) as connection:
                        connection.execute('BEGIN EXCLUSIVE');connection.rollback()
                        busy=connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]
                        if busy:raise AccountError('ACCOUNT_BUSY')
                for p in files:
                    if p.exists():p.unlink()
                folder.rmdir()
            db.execute("UPDATE accounts SET status='DELETED' WHERE id=?",(account_id,))
        return {'status':'DELETED','account_id':account_id}
