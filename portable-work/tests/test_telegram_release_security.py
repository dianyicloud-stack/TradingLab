"""Release authorization tests: synthetic IDs, fake token, fake transport only."""
from pathlib import Path
from unittest.mock import MagicMock,patch
import io,json,os,tempfile,unittest
from adapters.telegram import TelegramConfig,TelegramSender,load_config
from app.system.notifications import NotificationRouter,Notifications,TZ
from shared.config import ScopedStore
ROOT=Path(__file__).resolve().parents[2]
SYNTHETIC='100001';OTHER='100002';TOKEN='123:'+('x'*30)
class AuthorizationTests(unittest.TestCase):
 def setUp(self):
  parent=ROOT/'.dev/step04-fix-security';parent.mkdir(parents=True,exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=parent);self.root=Path(self.tmp.name).resolve();self.assertTrue(self.root.is_relative_to(parent.resolve()));self.addCleanup(self.tmp.cleanup)
  self.env={'TELEGRAM_NOTIFICATIONS_ENABLED':'true','TELEGRAM_BOT_TOKEN':TOKEN,'TELEGRAM_CHAT_ID':SYNTHETIC}
 def authorize(self,value=SYNTHETIC):
  (self.root/'.env.telegram').write_text('TELEGRAM_ALLOWED_CHAT_ID='+value+'\n',encoding='utf-8')
 def fake(self):
  opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=b'{"ok":true,"result":{"message_id":17}}';return opener
 def rejected(self,config,expected='INVALID_CHAT'):
  opener=self.fake();self.assertEqual(TelegramSender(config,opener).send('synthetic message')['state'],expected);opener.open.assert_not_called()
 def test_missing_authorization_refuses_send(self):self.rejected(load_config(self.root,environment=self.env))
 def test_missing_requested_recipient_refuses_send(self):
  self.authorize();self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_CHAT_ID':''}))
 def test_unapproved_recipient_refuses_send(self):
  self.authorize();self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_CHAT_ID':OTHER}))
 def test_environment_cannot_grant_authorization(self):
  self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_ALLOWED_CHAT_ID':SYNTHETIC}))
  self.authorize();self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_CHAT_ID':OTHER,'TELEGRAM_ALLOWED_CHAT_ID':OTHER}))
 def test_main_env_cannot_grant_authorization(self):
  (self.root/'.env').write_text('TELEGRAM_ALLOWED_CHAT_ID='+SYNTHETIC+'\n');self.rejected(load_config(self.root,environment=self.env))
 def test_authorized_target_uses_mocked_transport(self):
  self.authorize();config=load_config(self.root,environment=self.env);opener=self.fake()
  self.assertEqual(TelegramSender(config,opener).send('synthetic message'),{'state':'SENT','message_id':17})
  self.assertEqual(json.loads(opener.open.call_args.args[0].data)['chat_id'],SYNTHETIC)
 def test_authorization_is_single_positive_private_chat(self):
  for value in ('','0','-100001','@synthetic',SYNTHETIC+','+OTHER,'1'*17):
   with self.subTest(kind='invalid format'):
    self.authorize(value);self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_CHAT_ID':value}))
 def test_private_authorization_does_not_interpolate_environment(self):
  self.authorize('${TELEGRAM_CHAT_ID}')
  with patch.dict(os.environ,{'TELEGRAM_CHAT_ID':SYNTHETIC}):self.rejected(load_config(self.root,environment=self.env))
 def test_dev_and_test_do_not_read_private_files(self):
  self.authorize()
  for namespace in ('DEV','TEST'):
   with patch('adapters.telegram.dotenv_values',side_effect=AssertionError('must not read')):
    config=load_config(self.root,namespace,environment=self.env)
   self.rejected(config,'DISABLED');config.enabled=True;config.token=TOKEN;config.chat_id=SYNTHETIC;config.allowed_chat_id=SYNTHETIC
   self.rejected(config,'DISABLED')
 def test_direct_config_has_no_default_authorization(self):self.rejected(TelegramConfig(True,TOKEN,chat_id=SYNTHETIC))
 def test_disabled_or_missing_token_never_opens_transport(self):
  self.authorize()
  self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_BOT_TOKEN':''}),'NO_TOKEN')
  self.rejected(load_config(self.root,environment={**self.env,'TELEGRAM_NOTIFICATIONS_ENABLED':'false'}),'DISABLED')
 def test_unreadable_approval_fails_closed(self):
  self.authorize();from adapters.telegram import dotenv_values
  def read(path,**kw):
   if Path(path).name=='.env.telegram':raise PermissionError('synthetic')
   return dotenv_values(path,**kw)
  with patch('adapters.telegram.dotenv_values',side_effect=read):self.rejected(load_config(self.root,environment=self.env))
 def test_linked_authorization_is_not_trusted(self):
  source=self.root/'synthetic-approval';source.write_text('TELEGRAM_ALLOWED_CHAT_ID='+SYNTHETIC+'\n');os.link(source,self.root/'.env.telegram')
  self.rejected(load_config(self.root,environment=self.env))
 def test_old_queue_is_not_retargeted_after_local_authorization_change(self):
  self.authorize();config=load_config(self.root,environment=self.env)
  feed=MagicMock();feed.notification_boundary.return_value=0;feed.notification_completions.return_value=[]
  sender=MagicMock();sender.send.return_value={'state':'SENT','message_id':17}
  service=Notifications(ScopedStore(self.root/'store',boundary=self.root),config,sender,feed);self.addCleanup(service.close)
  day=service.clock().astimezone(TZ).date().isoformat()
  with service.db() as db:
   db.execute("INSERT INTO outbox(namespace,opinion_id,chat_id,channel,day,parts,status) VALUES('USER','old',?,'TELEGRAM',?,?,'PENDING')",(OTHER,day,json.dumps(['old synthetic message'])))
  service.tick();sender.send.assert_not_called()
  with service.db() as db:
   db.execute("INSERT INTO outbox(namespace,opinion_id,chat_id,channel,day,parts,status) VALUES('USER','current',?,'TELEGRAM',?,?,'PENDING')",(SYNTHETIC,day,json.dumps(['current synthetic message'])))
  service.tick();sender.send.assert_called_once_with('current synthetic message')
  with service.db() as db:self.assertEqual(db.execute("SELECT status FROM outbox WHERE opinion_id='old'").fetchone()[0],'PENDING')
 def test_api_cannot_select_recipient_and_status_is_redacted(self):
  self.authorize();config=load_config(self.root,environment=self.env)
  feed=MagicMock();feed.notification_boundary.return_value=0
  service=Notifications(ScopedStore(self.root/'store',boundary=self.root),config,MagicMock(),feed);self.addCleanup(service.close)
  router=NotificationRouter(service);self.assertFalse(router.accepts_post('/api/system/telegram'));self.assertIsNone(router.route('POST','/api/system/telegram',{'chat_id':OTHER}))
  status=router.route('GET','/api/system/telegram')[1];self.assertTrue(status['recipient_authorized']);self.assertNotIn('chat_id',status)
  self.assertNotIn(SYNTHETIC,json.dumps(status));self.assertNotIn(TOKEN,json.dumps(status));self.assertNotIn(SYNTHETIC,repr(config));self.assertNotIn(TOKEN,repr(config))
if __name__=='__main__':unittest.main()
