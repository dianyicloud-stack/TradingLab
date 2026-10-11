"""No network: real success path, isolated stores, Fake Telegram even with local Token."""
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import io,json,tempfile,time,unittest,urllib.error
from adapters.telegram import TelegramConfig,TelegramSender,load_config
from app.system.notifications import Notifications
from contracts.live.notification import format_opinion,split_message
from shared.config import ScopedStore
from tests.agent_auto_fixture import AgentAutoFixture

ROOT=Path(__file__).resolve().parents[1]
class FakeSender:
    def __init__(self,results=None):self.sent=[];self.results=list(results or [])
    def send(self,text):
        self.sent.append(text)
        return self.results.pop(0) if self.results else {'state':'SENT','message_id':100+len(self.sent)}

class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='notify-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.f=AgentAutoFixture(self.root);self.addCleanup(self.f.close)
        self.a=self.f.advisory;self.a.source='USER' # Isolated actual production callback, Fake provider/transport only.
        self.config=TelegramConfig(True,'123:'+('x'*30),chat_id='100001',allowed_chat_id='100001');self.sender=FakeSender()
        self.n=Notifications(ScopedStore(self.root/'notifications',boundary=self.root),self.config,self.sender,self.a,clock=lambda:self.f.now)
        self.addCleanup(self.n.close);self.a.success_observer=self.n.completed
    def auto(self):self.f.advance_native();self.f.auto_cycle();return self.a.latest('bj920161')
    def tick(self):self.n.next_send=0;self.n.tick()
    def test_actual_auto_commit_callback_and_boundary(self):
        op=self.auto();self.assertEqual(self.a.runtime.latest_request(op['tracking_session_id'])['status'],'COMPLETED')
        self.assertTrue(self.n.wake.is_set());self.tick();self.assertEqual(len(self.sender.sent),1)
        text=self.sender.sent[0];self.assertEqual(text,format_opinion(op));self.assertEqual(text.count('【'),3)
        for forbidden in ('WATCH','confidence','provider','account_id'):self.assertNotIn(forbidden,text)
        self.n.completed({'namespace':'USER','opinion_id':op['advisory_id']});self.tick();self.assertEqual(len(self.sender.sent),1)
        restarted=Notifications(self.n.store,self.config,self.sender,self.a,clock=lambda:self.f.now)
        restarted.tick();self.assertEqual(len(self.sender.sent),1)
        with restarted.db() as db:self.assertIsNone(db.execute('SELECT parts FROM outbox').fetchone()[0])
    def test_existing_history_not_backfilled(self):
        self.auto();new=Notifications(ScopedStore(self.root/'fresh',boundary=self.root),self.config,self.sender,self.a,clock=lambda:self.f.now)
        new.tick();self.assertEqual(self.sender.sent,[])
    def test_recovery_without_callback_browser_or_ai_repeat(self):
        self.a.success_observer=lambda e:(_ for _ in ()).throw(OSError())
        self.auto();calls=len(self.f.provider.calls);self.n.start()
        until=time.monotonic()+4
        while not self.sender.sent and time.monotonic()<until:time.sleep(.02)
        self.assertEqual(len(self.sender.sent),1);self.assertEqual(len(self.f.provider.calls),calls)
    def test_manual_success_sent_failed_test_simulation_filtered(self):
        self.f.advance_native();op=self.a.analyze('bj920161');self.tick();self.assertEqual(self.sender.sent,[format_opinion(op)])
        self.f.advance_native()
        with patch.object(self.f.provider,'analyze',side_effect=TimeoutError()):self.f.auto_cycle()
        self.tick();self.assertEqual(len(self.sender.sent),1)
        op={'runtime_mode':'SIMULATION','trigger_type':'AUTO_EVENT','session_date':self.f.now.date().isoformat()}
        self.assertFalse(self.n.eligible(op))
        test=Notifications(ScopedStore(self.root/'testnotice',boundary=self.root),self.config,self.sender,self.a,'TEST',clock=lambda:self.f.now)
        test.tick();self.assertFalse(test.eligible({**op,'runtime_mode':'LIVE'}))
    def test_manual_no_new_data_then_explicit_reanalysis(self):
        from contracts.live.bridge import BridgeError
        self.f.advance_native();op=self.a.analyze('bj920161');self.tick()
        with self.assertRaises(BridgeError) as caught:self.a.analyze('bj920161')
        self.assertEqual(caught.exception.code,'NO_NEW_ADVISORY_DATA');self.tick();self.assertEqual(len(self.sender.sent),1)
        again=self.a.analyze('bj920161',force=True);self.assertEqual(again['trigger_type'],'MANUAL_REANALYSIS')
        self.tick();self.assertEqual(self.sender.sent,[format_opinion(op),format_opinion(again)])
        self.n.completed({'namespace':'USER','opinion_id':again['advisory_id']});self.tick();self.assertEqual(len(self.sender.sent),2)
    def test_upgrade_does_not_backfill_manual_history(self):
        # Emulate existing AUTO-only installation without the new manual boundary.
        with self.n.db() as db:db.execute("DELETE FROM state WHERE key='manual_boundary'")
        self.f.advance_native();self.a.analyze('bj920161')
        upgraded=Notifications(self.n.store,self.config,self.sender,self.a,clock=lambda:self.f.now)
        upgraded.tick();self.assertEqual(self.sender.sent,[])
        self.f.advance_native();op=self.a.analyze('bj920161');upgraded.tick()
        self.assertEqual(self.sender.sent,[format_opinion(op)])
    def test_failure_does_not_damage_success_or_account_and_next_round(self):
        self.sender.results=[{'state':'UNKNOWN'}];op=self.auto();self.tick()
        cursor=self.a.runtime.cursor(op['tracking_session_id']);self.assertEqual(cursor['last_advisory_id'],op['advisory_id'])
        self.tick();self.assertEqual(len(self.sender.sent),1)
        self.auto();self.tick();self.assertEqual(len(self.sender.sent),2)
        self.assertEqual(self.n.status()['counts'],{'SENT':1,'UNKNOWN':1})
    def test_cross_day_cleanup_cursor_prevents_resend(self):
        self.auto();self.tick();self.f.now+=timedelta(days=8);self.tick()
        self.assertEqual(self.n.status()['counts'],{});self.assertEqual(len(self.sender.sent),1)
        self.n.completed({'namespace':'USER'});self.tick();self.assertEqual(len(self.sender.sent),1)
    def test_pending_expired_no_send(self):
        self.auto();self.n.recover();self.f.now+=timedelta(days=1);self.tick()
        self.assertEqual(self.sender.sent,[]);self.assertEqual(self.n.status()['counts'],{'EXPIRED':1})
    def test_disabled_notifications_still_expire_old_bodies(self):
        self.auto();self.n.recover();self.n.config.enabled=False;self.f.now+=timedelta(days=1);self.tick()
        self.assertEqual(self.sender.sent,[])
        with self.n.db() as db:self.assertIsNone(db.execute('SELECT parts FROM outbox').fetchone()[0])
    def test_multistock_long_split_order(self):
        self.f.prices['sh688601']+=2;self.auto();self.tick();self.tick();self.assertEqual(len(self.sender.sent),2)
        self.assertEqual(set(self.sender.sent),{format_opinion(self.a.latest(s)) for s in ('bj920161','sh688601')})
        text=format_opinion({'name':'测试','symbol':'bj920161','game_state':'如果价格不高于10.25元，不买入。😀'*500,'core_conflict':'否定条件必须保留','next_observation_focus':['量不足不确认']})
        chunks=split_message(text);self.assertEqual(''.join(chunks),text)
        self.assertTrue(all(len(x.encode('utf-16-le'))//2<=4096 for x in chunks));self.assertGreater(len(chunks),1)
    def test_long_saved_opinion_parts_survive_restart(self):
        original=self.f.provider.analyze
        def long_analysis(*args):
            result=original(*args);result['analysis']['game_state']='若未站稳10.30元，则不确认。'*150
            result['analysis']['core_conflict']='成交量不足时不能确认。'*100
            result['analysis']['next_observation_focus']=['10.10元失守则无效。'*50]*4
            return result
        with patch.object(self.f.provider,'analyze',side_effect=long_analysis):op=self.auto()
        self.tick();self.assertEqual(len(self.sender.sent),1)
        self.n=Notifications(self.n.store,self.config,self.sender,self.a,clock=lambda:self.f.now)
        for _ in range(10):self.tick()
        self.assertEqual(''.join(self.sender.sent),format_opinion(op))
        self.assertEqual(self.n.status()['counts'],{'SENT':1})
        self.assertTrue(all(len(t.encode('utf-16-le'))//2<=4096 for t in self.sender.sent))
    def test_saved_but_success_status_not_committed_not_notified(self):
        original=self.a.runtime.request_status
        def fail_commit(identity,status,*args):
            if status=='COMPLETED':raise OSError('isolated interrupted success commit')
            return original(identity,status,*args)
        with patch.object(self.a.runtime,'request_status',side_effect=fail_commit):self.auto()
        self.tick();self.assertEqual(self.sender.sent,[])
    def test_rate_limit_bounded_and_auth_halts(self):
        self.sender.results=[{'state':'RETRY','retry_after':60}]*3;self.auto();self.tick();self.tick();self.assertEqual(len(self.sender.sent),1)
        for _ in range(2):
            with self.n.db() as db:db.execute('UPDATE outbox SET not_before=0')
            self.tick()
        self.tick();self.assertEqual(len(self.sender.sent),3);self.assertEqual(self.n.status()['counts'],{'FAILED':1})
        self.sender.results=[{'state':'AUTH_ERROR'}];self.auto();self.tick();self.auto();self.tick()
        self.assertEqual(len(self.sender.sent),4);self.assertEqual(self.n.status()['state'],'AUTH_ERROR')
    def test_no_token_no_request(self):
        self.n.config.token='';self.auto();self.tick();self.assertEqual(self.sender.sent,[])
        self.assertEqual(self.n.status()['message'],'未配置Bot Token')
    def test_interrupted_send_is_unknown(self):
        self.auto();self.n.recover()
        with self.n.db() as db:db.execute("UPDATE outbox SET status='SENDING'")
        n=Notifications(self.n.store,self.config,self.sender,self.a,clock=lambda:self.f.now);n.tick()
        self.assertEqual(n.status()['counts'],{'UNKNOWN':1});self.assertEqual(self.sender.sent,[])

class TransportTests(unittest.TestCase):
    def test_response_and_error_semantics(self):
        from unittest.mock import MagicMock as Mock
        config=TelegramConfig(True,'123:'+('x'*30),chat_id='100001',allowed_chat_id='100001')
        for code,state in [(401,'AUTH_ERROR'),(403,'FORBIDDEN'),(400,'INVALID_MESSAGE'),(429,'RETRY'),(500,'UNKNOWN')]:
            opener=Mock();opener.open.side_effect=urllib.error.HTTPError('private',code,'private',{},io.BytesIO(json.dumps({'ok':False,'error_code':code,'parameters':{'retry_after':5}}).encode()))
            result=TelegramSender(config,opener).send('测试');self.assertEqual(result['state'],state);self.assertNotIn(config.token,str(result))
        opener=Mock();opener.open.side_effect=TimeoutError('secret');self.assertEqual(TelegramSender(config,opener).send('测试')['state'],'UNKNOWN')
        opener.open.side_effect=None;opener.open.return_value.__enter__.return_value.read.return_value=b'{"ok":true,"result":{"message_id":123}}'
        self.assertEqual(TelegramSender(config,opener).send('测试')['message_id'],123)
        opener.open.return_value.__enter__.return_value.read.return_value=b'{"ok":true,"result":{}}'
        self.assertEqual(TelegramSender(config,opener).send('测试')['state'],'UNKNOWN')
    def test_config_test_namespace_ignores_real_environment(self):
        self.assertEqual(load_config(ROOT,'TEST',{'TELEGRAM_BOT_TOKEN':'secret','TELEGRAM_NOTIFICATIONS_ENABLED':'true'}).state,'DISABLED')
        self.assertEqual(load_config(ROOT,environment={'TELEGRAM_BOT_TOKEN':'','TELEGRAM_NOTIFICATIONS_ENABLED':'true'}).state,'NO_TOKEN')
        self.assertEqual(load_config(ROOT,'TEST').env_path,str(ROOT/'.env'))
