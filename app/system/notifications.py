"""Bounded persistent outbox, independent of analysis/account transactions."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from threading import Event,Thread,Lock
import hashlib,json,sqlite3,time
from contracts.live.notification import format_opinion,split_message

LABELS={'DISABLED':'未启用','NO_TOKEN':'未配置Bot Token','INVALID_CHAT':'目标私聊配置不匹配',
 'READY':'等待新的自动或手动分析成功意见','SENT':'已确认送达','RETRY':'Telegram限流，等待重试',
 'AUTH_ERROR':'Bot Token无效，请修改配置后重启Web','FORBIDDEN':'Bot无权向此私聊发送，请先打开Bot并发送/start',
 'INVALID_MESSAGE':'Telegram拒绝消息参数，已停止重试','UNKNOWN':'是否送达未知，未自动重发',
 'EXPIRED':'跨日待发消息已过期','ERROR':'通知队列暂不可用，分析不受影响','FULL':'通知积压达到上限，恢复登记暂缓'}
TZ=timezone(timedelta(hours=8))

class Notifications:
    def __init__(self,store,config,sender,feed,namespace='USER',clock=None):
        self.store,self.config,self.sender,self.feed,self.namespace=store,config,sender,feed,namespace
        self.clock=clock or (lambda:datetime.now(timezone.utc));self.stop=Event();self.wake=Event();self.thread=None;self.lock=Lock();self.last='READY';self.next_send=0
        store.ensure()
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS outbox(namespace TEXT,opinion_id TEXT,chat_id TEXT,channel TEXT,day TEXT,
              parts TEXT,part INTEGER DEFAULT 0,attempts INTEGER DEFAULT 0,status TEXT,not_before REAL DEFAULT 0,receipts TEXT DEFAULT '[]',
              PRIMARY KEY(namespace,opinion_id,chat_id,channel));''')
            # The request may have reached Telegram before a process stopped.
            db.execute("UPDATE outbox SET status='UNKNOWN',parts=NULL WHERE status='SENDING'")
            key=hashlib.sha256((config.token+'|'+config.chat_id+'|'+config.proxy).encode()).hexdigest()
            old=db.execute("SELECT value FROM state WHERE key='config_hash'").fetchone()
            if not old or old[0]!=key:db.execute("DELETE FROM state WHERE key='blocked'")
            db.execute("INSERT OR REPLACE INTO state VALUES('config_hash',?)",(key,))
            if self.config.enabled and namespace=='USER' and not db.execute("SELECT 1 FROM state WHERE key='boundary'").fetchone():
                boundary=str(feed.notification_boundary())
                db.executemany('INSERT INTO state VALUES(?,?)',[('boundary',boundary),('cursor',boundary)])
            if self.config.enabled and namespace=='USER' and not db.execute("SELECT 1 FROM state WHERE key='manual_boundary'").fetchone():
                db.execute("INSERT INTO state VALUES('manual_boundary',?)",(str(feed.notification_boundary()),))
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.store.path('telegram.db'),timeout=3);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def eligible(self,opinion):
        return self.namespace=='USER' and self.config.enabled and opinion.get('runtime_mode')=='LIVE' and opinion.get('trigger_type') in ('AUTO_EVENT','MANUAL','MANUAL_REANALYSIS') and opinion.get('effective_result',True) and opinion.get('session_date')==self.clock().astimezone(TZ).date().isoformat()
    def completed(self,event):
        # Callback carries identity only; persisted completion and Opinion are read via Live owner.
        if event.get('namespace')!='USER':return
        self.wake.set()
    def recover(self):
        if self.namespace!='USER':return
        with self.db() as db:
            day=self.clock().astimezone(TZ).date().isoformat()
            db.execute("UPDATE outbox SET parts=NULL,status='EXPIRED' WHERE day<>? AND status IN ('PENDING','RETRY')",(day,))
            db.execute('DELETE FROM outbox WHERE day<?',((self.clock().astimezone(TZ).date()-timedelta(days=7)).isoformat(),))
            if not self.config.enabled:return
            cursor=db.execute("SELECT value FROM state WHERE key='cursor'").fetchone()
            if not cursor:return
            cursor=int(cursor[0])
        rows=self.feed.notification_completions(cursor,100)
        with self.db() as db:
            manual_boundary=int(db.execute("SELECT value FROM state WHERE key='manual_boundary'").fetchone()[0])
            # Cursor never resets; old identities cannot be re-enqueued by recovery.
            for row in rows:
                if row['status'] in ('QUEUED','RUNNING'):break
                op=row.get('opinion')
                new_trigger=op and (op.get('trigger_type')=='AUTO_EVENT' or row['sequence']>manual_boundary)
                if new_trigger and row['status']=='COMPLETED' and self.eligible(op):
                    if db.execute("SELECT count(*) FROM outbox WHERE parts IS NOT NULL").fetchone()[0]>=1000:self.last='FULL';break
                    db.execute("INSERT OR IGNORE INTO outbox(namespace,opinion_id,chat_id,channel,day,parts,status) VALUES(?,?,?,'TELEGRAM',?,?,'PENDING')",
                        (self.namespace,op['advisory_id'],self.config.chat_id,op['session_date'],json.dumps(split_message(format_opinion(op)),ensure_ascii=False)))
                cursor=row['sequence'];db.execute("UPDATE state SET value=? WHERE key='cursor'",(str(cursor),))
    def tick(self):
        if not self.lock.acquire(False):return
        try:
            self.recover()
            if self.namespace!='USER' or self.config.state!='READY':return
            with self.db() as db:
                if db.execute("SELECT 1 FROM state WHERE key='blocked' AND value='1'").fetchone():return
                # Oldest pending part holds the chat lane, including retry_after.
                row=db.execute("SELECT rowid,* FROM outbox WHERE namespace=? AND chat_id=? AND status IN ('PENDING','RETRY') ORDER BY rowid LIMIT 1",(self.namespace,self.config.chat_id)).fetchone()
                if not row or time.time()<row['not_before'] or time.monotonic()<self.next_send:return
                db.execute("UPDATE outbox SET status='SENDING',attempts=attempts+1 WHERE rowid=?",(row['rowid'],))
            self.next_send=time.monotonic()+1.1
            try:result=self.sender.send(json.loads(row['parts'])[row['part']])
            except Exception:result={'state':'UNKNOWN'}
            state=result['state'];self.last=state
            with self.db() as db:
                if state=='SENT':
                    receipts=json.loads(row['receipts'])+[result['message_id']];part=row['part']+1
                    done=part==len(json.loads(row['parts']))
                    db.execute('UPDATE outbox SET status=?,part=?,attempts=0,parts=?,receipts=? WHERE rowid=?',('SENT' if done else 'PENDING',part,None if done else row['parts'],json.dumps(receipts),row['rowid']))
                elif state=='RETRY' and row['attempts']<2:
                    db.execute("UPDATE outbox SET status='RETRY',not_before=? WHERE rowid=?",(time.time()+result['retry_after'],row['rowid']))
                else:
                    db.execute('UPDATE outbox SET status=?,parts=NULL WHERE rowid=?',(state if state!='RETRY' else 'FAILED',row['rowid']))
                    if state in ('AUTH_ERROR','FORBIDDEN','INVALID_MESSAGE'):
                        db.execute("INSERT OR REPLACE INTO state VALUES('blocked','1')")
        finally:self.lock.release()
    def status(self):
        with self.db() as db:
            counts=dict(db.execute('SELECT status,count(*) FROM outbox GROUP BY status'))
            last=db.execute('SELECT status,receipts FROM outbox ORDER BY rowid DESC LIMIT 1').fetchone()
            blocked=db.execute("SELECT 1 FROM state WHERE key='blocked' AND value='1'").fetchone()
            error=db.execute("SELECT status FROM outbox WHERE status IN ('AUTH_ERROR','FORBIDDEN','INVALID_MESSAGE') ORDER BY rowid DESC LIMIT 1").fetchone()
        state=self.config.state if self.config.state!='READY' else self.last
        if self.config.state=='READY' and blocked and error:state=error[0]
        return {'state':state,'message':LABELS.get(state,state),'env_path':self.config.env_path,'enabled':self.config.enabled,
                'recipient_authorized':self.config.state=='READY','triggers':['AUTO_EVENT','MANUAL','MANUAL_REANALYSIS'],'counts':counts,'last_delivery':dict(last) if last else None}
    def start(self):
        if self.thread:return
        def work():
            while not self.stop.is_set():
                try:self.tick()
                except Exception:self.last='ERROR'
                self.wake.wait(2);self.wake.clear()
        self.thread=Thread(target=work,name='TradingLab-Telegram',daemon=True);self.thread.start()
    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join(15)

class NotificationRouter:
    def __init__(self,service):self.service=service
    def accepts_post(self,path):return False
    def start_maintenance(self):self.service.start()
    def close(self):self.service.close()
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/api/system/telegram':return 200,self.service.status(),None
