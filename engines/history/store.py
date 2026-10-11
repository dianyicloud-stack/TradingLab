"""Bounded owner-local working cache and immutable successful historical opinions."""
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from collections import OrderedDict
import json,sqlite3
from datetime import timedelta,date,datetime
from contracts.history.bars import HistoryError
from shared.serialization import digest

class HistoryStore:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'history.db'
        self.lock=Lock();self.expiry_lock=Lock();self.flights={}
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS daily(symbol TEXT PRIMARY KEY,day TEXT,count INTEGER,body TEXT,used_at TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,request_id TEXT UNIQUE,created_at TEXT,used_day TEXT,status TEXT,context TEXT,input TEXT,opinion TEXT,error TEXT);
            CREATE TABLE IF NOT EXISTS preferences(symbol TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE IF NOT EXISTS maintenance(key TEXT PRIMARY KEY,value TEXT);
            CREATE TRIGGER IF NOT EXISTS immutable_history_success BEFORE UPDATE ON jobs WHEN OLD.status='SUCCEEDED' AND NEW.status!='EXPIRED' BEGIN SELECT RAISE(ABORT,'IMMUTABLE_HISTORY_OPINION');END;''')
            db.execute("UPDATE jobs SET status='INTERRUPTED',error='服务重启前任务未完成，未自动重试。' WHERE status IN ('QUEUED','RUNNING')")
            db.executescript('''CREATE TABLE IF NOT EXISTS result_index(
                id TEXT PRIMARY KEY,day TEXT NOT NULL,symbol TEXT NOT NULL,name TEXT,
                context_key TEXT NOT NULL,data_version TEXT,provider TEXT,model TEXT,reasoning TEXT,completed_at TEXT);
                CREATE INDEX IF NOT EXISTS history_today ON result_index(day,completed_at,id);
                CREATE INDEX IF NOT EXISTS history_same_context ON result_index(day,context_key);''')
            # Upgrade saved successes without changing immutable input or Opinion bytes.
            for r in db.execute("SELECT * FROM jobs WHERE status='SUCCEEDED' AND id NOT IN (SELECT id FROM result_index)").fetchall():
                f=json.loads(r['input']);o=json.loads(r['opinion']);q=json.loads(r['context'])
                key=self.context_key(q,f['data_version'],o['provider'],o['model'],o.get('reasoning','none'))
                db.execute('INSERT INTO result_index VALUES(?,?,?,?,?,?,?,?,?,?)',(r['id'],r['used_day'],q['symbol'],o.get('name'),key,f['data_version'],o['provider'],o['model'],o.get('reasoning','none'),o['generated_at']))
    @staticmethod
    def context_key(q,version,provider,model,reasoning):
        return digest({'request':q,'data_version':version,'provider':provider,'model':model,'reasoning':reasoning})
    def matching(self,day,key):
        with self.db() as db:
            row=db.execute("SELECT j.id FROM jobs j JOIN result_index i ON i.id=j.id WHERE i.day=? AND i.context_key=? AND j.status IN ('SUCCEEDED','RUNNING','QUEUED') ORDER BY CASE WHEN j.status='SUCCEEDED' THEN 0 ELSE 1 END,i.completed_at DESC LIMIT 1",(day,key)).fetchone()
        return self.job(row[0]) if row else None
    def today(self,day,before=None,limit=20):
        import base64
        where="i.day=? AND j.status='SUCCEEDED'";args=[day]
        if before:
            try:
                stamp,identity=json.loads(base64.urlsafe_b64decode(before.encode()).decode())
                if not isinstance(stamp,str) or not isinstance(identity,str):raise ValueError()
            except (ValueError,TypeError,UnicodeError):raise HistoryError('INVALID_CURSOR','历史列表分页位置无效。',400) from None
            where+=' AND (i.completed_at<? OR (i.completed_at=? AND i.id<?))';args.extend((stamp,stamp,identity))
        with self.db() as db:
            count=db.execute("SELECT count(*) FROM result_index i JOIN jobs j ON j.id=i.id WHERE i.day=? AND j.status='SUCCEEDED'",(day,)).fetchone()[0]
            rows=db.execute('SELECT i.*,j.context,j.created_at,j.status FROM result_index i JOIN jobs j ON j.id=i.id WHERE '+where+' ORDER BY i.completed_at DESC,i.id DESC LIMIT ?',(*args,limit+1)).fetchall()
        more=len(rows)>limit;items=[]
        for r in rows[:limit]:
            item=dict(r);q=json.loads(item.pop('context'));item.update(q,analysis_id=item['id'],context_id=item['id'],opinion_id=item['id'],name=item['name'] or '名称未提供')
            items.append(item)
        cursor=base64.urlsafe_b64encode(json.dumps([items[-1]['completed_at'],items[-1]['id']]).encode()).decode() if more else None
        return {'day':day,'total':count,'items':items,'next_cursor':cursor}
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def daily(self,symbol,count,adapter,now):
        # Per-symbol single-flight, no Agent/source lock held during HTTP.
        with self.lock:
            if symbol not in self.flights:
                if len(self.flights)>=64:raise HistoryError('HISTORY_BUSY','历史请求过多，请稍后重试。',429)
                self.flights[symbol]=[Lock(),0]
            entry=self.flights[symbol];entry[1]+=1
        try:
            with entry[0]:
                day=now.date().isoformat();stamp=now.isoformat()
                with self.db() as db:row=db.execute('SELECT * FROM daily WHERE symbol=?',(symbol,)).fetchone()
                fresh=row and ((now-datetime.fromisoformat(row['used_at'])).total_seconds()<300 or datetime.fromisoformat(row['used_at']).strftime('%H:%M')>='15:00')
                if row and row['day']==day and row['count']>=count and fresh and not (now.strftime('%H:%M')>='15:00' and datetime.fromisoformat(row['used_at']).strftime('%H:%M')<'15:00'):
                    return json.loads(row['body'])
                result=adapter.fetch(symbol,count)
                body=json.dumps(result,ensure_ascii=False,allow_nan=False)
                if len(body.encode())>2*1024*1024:raise HistoryError('CACHE_SIZE_LIMIT','日线响应超出工作缓存上限。')
                with self.db() as db:
                    db.execute('INSERT OR REPLACE INTO daily VALUES(?,?,?,?,?)',(symbol,day,count,body,stamp))
                    db.execute('DELETE FROM daily WHERE symbol IN (SELECT symbol FROM daily ORDER BY used_at DESC LIMIT -1 OFFSET 16)')
                return result
        finally:
            with self.lock:
                entry[1]-=1
                if not entry[1]:self.flights.pop(symbol,None)
    def job(self,identity):
        with self.db() as db:row=db.execute('SELECT * FROM jobs WHERE id=?',(identity,)).fetchone()
        if not row:raise HistoryError('HISTORY_NOT_FOUND','历史分析不存在或已过期。',404)
        value=dict(row)
        with self.db() as db:meta=db.execute('SELECT * FROM result_index WHERE id=?',(identity,)).fetchone()
        value['metadata']=dict(meta) if meta else {}
        for key in ('context','input','opinion'):
            value[key]=json.loads(value[key]) if value[key] else None
        if value['status']=='EXPIRED':value['message']='已按保留策略清理'
        return value
    def expire(self,keep_day):
        """History-only local-day TTL; never touches realtime/account owners."""
        with self.expiry_lock:return self._expire(keep_day)
    def _expire(self,keep_day):
        date.fromisoformat(keep_day)
        with self.db() as db:
            pending=db.execute("SELECT value FROM maintenance WHERE key='pending_expiry'").fetchone()
            ids=json.loads(pending[0]) if pending else [r[0] for r in db.execute("SELECT id FROM jobs WHERE used_day<? AND status NOT IN ('RUNNING','QUEUED','EXPIRED') LIMIT 100",(keep_day,))]
            db.execute('INSERT OR REPLACE INTO maintenance VALUES(?,?)',('pending_expiry',json.dumps(ids)))
            for identity in ids:db.execute("UPDATE jobs SET status='EXPIRED',input=NULL,opinion=NULL,error=NULL WHERE id=?",(identity,))
            db.executemany('DELETE FROM result_index WHERE id=?',[(s,) for s in ids])
            daily=db.execute('DELETE FROM daily WHERE day<?',(keep_day,)).rowcount
            db.execute('INSERT OR REPLACE INTO maintenance VALUES(?,?)',('last_keep_day',keep_day))
        from engines.live.provider_request_repository import expire_inputs
        expire_inputs(self.root/'provider_requests/provider_requests.db',ids)
        for identity in ids:
            # Exact generated, owner-local task budget files, no traversal.
            path=self.root/'attempts'/(identity+'.db')
            if path.exists():path.unlink()
        with self.db() as db:
            db.execute("DELETE FROM maintenance WHERE key='pending_expiry'")
            db.execute("DELETE FROM jobs WHERE status='EXPIRED' AND used_day<?",((date.fromisoformat(keep_day)-timedelta(days=30)).isoformat(),))
        return {'daily_cache_rows':daily,'historical_jobs_expired':len(ids),'keep_day':keep_day}
