from pathlib import Path
import tempfile,unittest
from unittest.mock import patch,Mock
from app.system import runtime_desktop as desktop
from app.system.runtime_state import RuntimeState,atomic

class DesktopTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='tradinglab-desktop-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
    def running(self):
        return {'status':'RUNNING','desired':{'listener':'ENABLED','startup':'MANUAL'},
            'services':{'web':{'actual':'RUNNING','runtime':{'listener':{'reason':'NON_TRADING_DAY'}}},'agent':{'actual':'RUNNING'}}}
    def test_chinese_status_does_not_expose_internal_diagnostics(self):
        state=self.running();state['token']='SECRET';state['supervisor']={'pid':987654}
        value=desktop.format_status(state,{'binding':{'name':'账户一','mode':'AUTO_SHADOW_EXECUTION','new_risk_paused':False},
            'model':{'provider':'deepseek','model':'deepseek-v4-pro','reasoning_effort':'low'},
            'telegram':{'enabled':True,'configured':True}})
        for expected in ('休市等待','期望状态：开启','账户一','自动影子执行','已关闭','低'):self.assertIn(expected,value)
        for secret in ('SECRET','987654','AUTO_SHADOW_EXECUTION'):self.assertNotIn(secret,value)
    def test_browser_once_per_instance_and_retry_after_failure(self):
        record={'instance_id':'one','url':'http://127.0.0.1:8765'};opener=Mock(return_value=False)
        self.assertEqual(desktop.open_once(self.root,record,opener),'OPEN_FAILED')
        opener.return_value=True
        self.assertEqual(desktop.open_once(self.root,record,opener),'OPENED')
        self.assertEqual(desktop.open_once(self.root,record,opener),'ALREADY_OPENED')
        self.assertEqual(opener.call_count,2)
        self.assertEqual(desktop.open_once(self.root,{**record,'instance_id':'two'},opener),'OPENED')
    def test_browser_exception_is_not_background_failure(self):
        self.assertEqual(desktop.open_once(self.root,{'instance_id':'one','url':'http://127.0.0.1:8765'},Mock(side_effect=OSError('no browser'))),'OPEN_FAILED')
    def test_running_start_reuses_services_and_browser_failure_returns_success(self):
        atomic(self.root/'runtime/web-instance.json',{'instance_id':'one','url':'http://127.0.0.1:8765'})
        with patch.object(desktop,'snapshot',return_value=self.running()),patch.object(desktop,'control_request') as control,patch.object(desktop,'ensure_supervisor') as ensure,patch.object(desktop,'web_get',return_value={'instance_id':'one'}),patch.object(desktop,'business_summary'),patch.object(desktop,'open_once',return_value='OPEN_FAILED'):
            output=Mock();self.assertEqual(desktop.run(self.root,self.root,'start',emit=output),0)
            control.assert_not_called();ensure.assert_not_called()
            self.assertTrue(any('后台已启动' in call.args[0] for call in output.call_args_list))
    def test_normal_stop_uses_existing_contract_preserves_listener(self):
        state=RuntimeState(self.root);state.update({'listener':'ENABLED'});before=state.read()
        with patch.object(desktop,'snapshot',return_value=self.running()),patch.object(desktop,'business_summary'),patch.object(desktop,'control_request',return_value={'operation':{'id':'op'}}) as control,patch.object(desktop,'wait_result') as wait:
            self.assertEqual(desktop.run(self.root,self.root,'stop',emit=Mock()),0)
            control.assert_called_once_with(self.root,{'action':'stop','target':'background'})
            wait.assert_called_once();self.assertEqual(before,state.read())
    def test_wait_blocked_and_timeout_are_bounded_no_force(self):
        with patch.object(desktop,'control_request',return_value={'operations':[{'id':'op','status':'BLOCKED','reason':'GRACEFUL_DRAIN_PENDING_NO_FORCE_USED'}]}) as control:
            with self.assertRaisesRegex(RuntimeError,'未强制'):desktop.wait_result(self.root,{'id':'op'},'stop',Mock())
            self.assertEqual(control.call_count,1)
        with self.assertRaisesRegex(RuntimeError,'等待超时'):desktop.wait_result(self.root,{'id':'op'},'start',Mock(),timeout=0)
    def test_wait_completed(self):
        status={'operations':[{'id':'op','status':'COMPLETED'}]}
        with patch.object(desktop,'control_request',return_value=status):self.assertEqual(desktop.wait_result(self.root,{'id':'op'},'start'),status)
    def test_offline_status_reads_saved_intent_without_starting(self):
        RuntimeState(self.root).update({'listener':'ENABLED'})
        with patch.object(desktop,'control_request',side_effect=OSError()),patch.object(desktop,'Supervisor') as supervisor,patch.object(desktop,'alive',return_value=False):
            supervisor.return_value.inspect.return_value={'actual':'STOPPED'}
            value=desktop.snapshot(self.root,self.root)
            self.assertEqual(value['status'],'STOPPED');self.assertEqual(value['desired']['listener'],'ENABLED')
            supervisor.return_value.tick.assert_not_called()
    def test_offline_cache_is_explicitly_historical(self):
        atomic(self.root/'runtime/desktop-status.json',{'measured_at':'earlier','binding':{'name':'账户一'}})
        with patch.object(desktop,'alive',return_value=False):value,cached=desktop.business_summary(self.root)
        self.assertTrue(cached);self.assertIn('本次未重新核对',desktop.format_status(self.running(),value,cached))
    def test_business_cache_filters_tokens(self):
        atomic(self.root/'runtime/web-instance.json',{'instance_id':'one'})
        replies=[{'instance_id':'one'},{'name':'账户一','mode':'ADVISORY_ONLY','new_risk_paused':True,'secret':'secret'},
            {'default':{'model':'model','api_key':'secret'}},{'state':'READY','enabled':True,'token':'secret'}]
        with patch.object(desktop,'alive',return_value=True),patch.object(desktop,'web_get',side_effect=replies):value,cached=desktop.business_summary(self.root)
        self.assertFalse(cached);self.assertNotIn('secret',(self.root/'runtime/desktop-status.json').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
