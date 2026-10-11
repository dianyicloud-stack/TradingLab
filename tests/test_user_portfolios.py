"""User portfolio contracts; isolated owners, real engine and deterministic market clock."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib,json,sqlite3,tempfile,unittest
from uuid import uuid4
from contracts.account.portfolio import AccountError
from shared.config import ScopedStore
from engines.account.engine import AccountEngine
from engines.account.ledger import AccountRepository,canonical
from engines.account.rules import DEFAULT_POLICY
from app.account.portfolio import PortfolioService
from app.account.portfolio_router import PortfolioRouter
from tests.account_fixture import policy,quote
from tests.test_shadow_drill import ShadowDrill

RESULTS={}
class UserPortfolios(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=ScopedStore(self.root,boundary=self.root)
        self.now='2026-09-18T10:00:00+08:00';self.prices={'bj920161':10,'sh688601':10};self.stale=False
        owner=self
        class Quotes:
            def clock(self,account,time):return time
            def quote(self,account,symbol,time):return quote(symbol,owner.prices.get(symbol,10),'2026-09-18T09:30:00+08:00' if owner.stale else time)
        self.quotes=Quotes();self.p=self.service();self.router=PortfolioRouter(self.p)
    def service(self):
        return PortfolioService(AccountEngine(AccountRepository(self.store)),self.quotes,namespace='TEST',clock=lambda:self.now)
    def create(self,name='组合',capital=200000,**overrides):
        return self.p.create({'name':name,'idempotency_key':uuid4().hex,'initial_capital':capital,'policy':policy(**overrides)})
    def bind(self,a):return self.p.bind({'account_id':a['account_id'] if a else None,'binding_version':self.p.binding()['binding_version']})
    def settings(self,a,**payload):return self.p.settings(a['account_id'],{**payload,'account_state_version':self.p.engine.state(a['account_id'])['account_state_version']})
    def advice(self,action='OPEN',target=.25,symbol='bj920161'):
        frozen={'source_namespace':'TEST','portfolio_context':self.p.context(symbol,refresh=False),'input_hash':uuid4().hex}
        opinion={'advisory_id':uuid4().hex,'runtime_mode':'LIVE','session_date':self.now[:10],'symbol':symbol,'core_conflict':'合成证据', 'portfolio_plan':{'portfolio_action':action,'target_weight':target},'trigger_type':'MANUAL'}
        return opinion,frozen
    def execute(self,action='OPEN',target=.25,symbol='bj920161'):
        return self.p.on_advisory(*self.advice(action,target,symbol))
    def test_creation_names_idempotency_cap_and_no_binding(self):
        payload={'name':'资金池','initial_capital':200000,'policy':deepcopy(DEFAULT_POLICY),'idempotency_key':'same'}
        a=self.p.create(payload);b=self.p.create(payload);self.assertEqual(a['account_id'],b['account_id']);self.assertIsNone(self.p.binding()['account_id'])
        for bad in (0,-1,200000.01,True):
            with self.assertRaises(AccountError):self.p.create({**payload,'initial_capital':bad,'idempotency_key':str(bad)})
        with self.assertRaises(AccountError):self.p.create({**payload,'name':''})
        with self.assertRaises(AccountError):self.p.create({**payload,'initial_capital':1})
        with self.assertRaises(AccountError):self.settings(a,initial_capital=1)
        self.settings(a,name='新名称');self.assertEqual(self.service().catalog()[0]['name'],'新名称')
    def test_profit_not_capped_and_two_symbols_shared_cash(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION',max_new_exposure_per_day_pct=.8);self.bind(a)
        x=self.execute();y=self.execute(symbol='sh688601');state=self.p.state(a['account_id'])
        self.assertEqual(len(state['positions']),2);self.assertEqual(state['cash'],round(200000-x['gross_amount']-y['gross_amount']-x['fees']['total']-y['fees']['total'],2))
        self.prices={'bj920161':20,'sh688601':20};state=self.p.state(a['account_id']);self.assertGreater(state['total_equity'],200000)
        b=self.create('独立账户');self.assertEqual(b['cash'],200000);self.assertEqual(self.p.binding()['account_id'],a['account_id'])
        RESULTS['two_symbols']={'cash':state['cash'],'positions':{k:v['qty'] for k,v in state['positions'].items()},'equity_after_rise':state['total_equity'],'other_account_cash':b['cash']}
    def test_modes_unbound_namespace_history_and_no_action(self):
        self.assertEqual(self.execute()['reason'],'NO_EXECUTION_ACCOUNT')
        a=self.create();self.bind(a);self.assertEqual(self.execute()['status'],'WAITING_HUMAN_CONFIRMATION')
        self.settings(a,policy=policy(ai_execution_mode='OFF'));self.assertEqual(self.execute()['status'],'OFF')
        self.settings(a,policy=policy(ai_execution_mode='AUTO_SHADOW_EXECUTION'))
        for mode in ('HISTORY_EOD','REPLAY','TEST'):
            op,f=self.advice();op['runtime_mode']=mode;self.assertEqual(self.p.on_advisory(op,f)['status'],'IGNORED')
        op,f=self.advice();f['source_namespace']='USER';self.assertEqual(self.p.on_advisory(op,f)['reason'],'ACCOUNT_NAMESPACE_MISMATCH')
        self.assertEqual(self.execute('NONE',0)['reason'],'NO_EXECUTION_ACTION');self.assertFalse(self.p.engine.state(a['account_id'])['executions'])
    def test_switch_version_fences_old_task_in_both_accounts(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION');b=self.create('B',ai_execution_mode='AUTO_SHADOW_EXECUTION');v=self.bind(a);op,f=self.advice();self.bind(b)
        self.assertEqual(self.p.on_advisory(op,f)['reason'],'ACCOUNT_BINDING_CHANGED')
        with self.assertRaises(AccountError):self.p.bind({'account_id':a['account_id'],'binding_version':v['binding_version']})
        self.bind(a);self.assertEqual(self.p.on_advisory(op,f)['reason'],'ACCOUNT_BINDING_CHANGED')
        self.assertFalse(self.p.engine.state(a['account_id'])['executions']);self.assertFalse(self.p.engine.state(b['account_id'])['executions'])
    def test_context_freeze_cannot_mix_account_a_with_binding_b(self):
        from threading import Event
        a=self.create('A');b=self.create('B');self.bind(a);entered=Event();release=Event();attempt=Event();original=self.p.engine.context
        def slow(*args):
            entered.set();self.assertTrue(release.wait(3));return original(*args)
        self.p.engine.context=slow
        def switch():attempt.set();return self.bind(b)
        with ThreadPoolExecutor(2) as pool:
            ctx=pool.submit(lambda:self.p.context('bj920161',refresh=False));self.assertTrue(entered.wait(3));sw=pool.submit(switch);self.assertTrue(attempt.wait(3));self.assertFalse(sw.done());release.set();frozen=ctx.result();current=sw.result()
        self.assertEqual(frozen['account_id'],a['account_id']);self.assertNotEqual(frozen['binding_version'],current['binding_version'])

    def test_delete_physical_unbind_restart_same_name_late_task(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION');self.bind(a);op,f=self.advice();self.execute();path=self.p.engine.repository.path(a['account_id'])
        self.p.delete(a['account_id'],{'confirmed':True});self.assertFalse(path.parent.exists());self.assertIsNone(self.p.binding()['account_id'])
        self.p.delete(a['account_id'],{'confirmed':True});self.p=self.service();b=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION');self.bind(b)
        self.assertNotEqual(a['account_id'],b['account_id']);self.assertEqual(self.p.on_advisory(op,f)['reason'],'ACCOUNT_BINDING_CHANGED');self.assertEqual(b['cash'],200000)
        with self.assertRaises(AccountError):self.p.engine.repository.create('LIVE_SHADOW',1,policy(),account_id=a['account_id'])
        with closing(sqlite3.connect(self.p.control.path)) as db:self.assertEqual(db.execute('select metadata from accounts where id=?',(a['account_id'],)).fetchone()[0],'{}')
    def test_target_sequence_repeat_conflicts_t1_and_restart(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION',max_position_weight_per_symbol=.8,max_total_exposure_pct=.9,max_new_exposure_per_day_pct=.8);self.bind(a)
        x=self.execute('OPEN',.15);q1=x['executed_qty'];op,f=self.advice('ADD',.3);x=self.p.on_advisory(op,f);self.assertTrue(self.p.on_advisory(op,f)['duplicate']);q2=self.p.state(a['account_id'])['positions']['bj920161']['qty'];self.assertGreater(q2,q1)
        repeat=self.execute('ADD',.3);self.assertEqual(repeat['executed_qty'],0)
        self.assertEqual(self.execute('OPEN',.4)['reason'],'ACTION_POSITION_CONFLICT');self.assertEqual(self.execute('REDUCE',.5)['reason'],'ACTION_TARGET_CONFLICT');self.assertEqual(self.execute('EXIT',.1)['reason'],'ACTION_TARGET_CONFLICT')
        self.assertEqual(self.execute('REDUCE',.1)['reason'],'T1_LOCK')
        self.now='2026-09-21T10:00:00+08:00';reduced=self.execute('REDUCE',.1);self.assertGreater(reduced['executed_qty'],0);self.p=self.service();closed=self.execute('EXIT',0);self.assertGreater(closed['executed_qty'],0);state=self.p.state(a['account_id']);self.assertFalse(state['positions']);self.assertGreaterEqual(state['cash'],0)
        RESULTS['target_path']={'open_qty':q1,'after_add_qty':q2,'reduce_qty':reduced['executed_qty'],'exit_qty':closed['executed_qty'],'final_cash':state['cash'],'realized_pnl':state['realized_pnl']}
    def test_pause_persistent_sells_mode_t1_no_replay(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION');self.bind(a);self.settings(a,new_risk_paused=True);self.assertEqual(self.execute()['reason'],'NEW_RISK_PAUSED');self.p=self.service();self.assertTrue(self.p.binding()['new_risk_paused'])
        self.settings(a,new_risk_paused=False);self.assertFalse(self.p.state(a['account_id'])['positions']);self.execute();self.settings(a,new_risk_paused=True);self.assertEqual(self.execute('ADD',.3)['reason'],'NEW_RISK_PAUSED');self.assertEqual(self.execute('EXIT',0)['reason'],'T1_LOCK')
        self.now='2026-09-21T10:00:00+08:00';self.settings(a,policy=policy());self.assertEqual(self.execute('EXIT',0)['status'],'WAITING_HUMAN_CONFIRMATION');self.settings(a,policy=policy(ai_execution_mode='AUTO_SHADOW_EXECUTION'));self.assertGreater(self.execute('EXIT',0)['executed_qty'],0)
    def test_pause_restore_does_not_resurrect_pre_pause_input(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION');self.bind(a)
        self.settings(a,new_risk_paused=True);self.settings(a,new_risk_paused=False)
        op,f=self.advice();self.settings(a,new_risk_paused=True);self.settings(a,new_risk_paused=False)
        self.assertEqual(self.p.on_advisory(op,f)['reason'],'ACCOUNT_STATE_CHANGED');self.assertFalse(self.p.state(a['account_id'])['positions'])

    def test_concurrent_buys_pause_and_delete_order(self):
        a=self.create(capital=10000,max_position_weight_per_symbol=1,max_total_exposure_pct=1,max_new_exposure_per_day_pct=1,minimum_cash_reserve_pct=0)
        def buy(symbol):return self.p.submit(a['account_id'],{'symbol':symbol,'portfolio_action':'OPEN','target_weight':.8,'source':'LIVE_MANUAL','source_ref':symbol})
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(buy,['bj920161','sh688601']))
        state=self.p.state(a['account_id']);self.assertGreaterEqual(state['cash'],0);self.assertGreaterEqual(len(state['positions']),1);self.assertTrue(all(r['executed_qty']>=0 for r in results))
        self.settings(a,new_risk_paused=True)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.p.submit(a['account_id'],{'symbol':'bj920161','portfolio_action':'ADD','target_weight':.9,'source':'LIVE_MANUAL','source_ref':uuid4().hex}),range(2)))
        self.assertTrue(all(x['reason']=='NEW_RISK_PAUSED' for x in results));RESULTS['shared_cash_concurrency']={'cash':state['cash'],'positions':{k:v['qty'] for k,v in state['positions'].items()}}
    def test_pause_and_commit_have_a_single_order(self):
        from threading import Event
        a=self.create();entered=Event();release=Event();pause_attempt=Event();original=self.p.engine._policy_execute
        def slow(*args):
            entered.set();self.assertTrue(release.wait(3));return original(*args)
        self.p.engine._policy_execute=slow
        def buy():return self.p.submit(a['account_id'],{'symbol':'bj920161','portfolio_action':'OPEN','target_weight':.2,'source':'LIVE_MANUAL','source_ref':'concurrent'})
        def pause():
            pause_attempt.set()
            with self.p._execution_lock:
                return self.settings(a,new_risk_paused=True)
        with ThreadPoolExecutor(2) as pool:
            trade=pool.submit(buy);self.assertTrue(entered.wait(3));paused=pool.submit(pause);self.assertTrue(pause_attempt.wait(3));self.assertFalse(paused.done());release.set()
            result=trade.result();after=paused.result()
        self.assertGreater(result['executed_qty'],0);self.assertTrue(after['new_risk_paused'])
        next_result=self.p.submit(a['account_id'],{'symbol':'bj920161','portfolio_action':'ADD','target_weight':.3,'source':'LIVE_MANUAL','source_ref':'after-pause'})
        self.assertEqual(next_result['reason'],'NEW_RISK_PAUSED')

    def test_off_hours_stale_quote_old_opinion_and_missing_valuation(self):
        a=self.create(ai_execution_mode='AUTO_SHADOW_EXECUTION');self.bind(a);self.stale=True;self.assertEqual(self.execute()['reason'],'STALE_QUOTE');self.stale=False
        op,f=self.advice();op['session_date']='2026-09-17';self.assertEqual(self.p.on_advisory(op,f)['reason'],'READY_FOR_REEVALUATION')
        self.now='2026-09-18T16:00:00+08:00';self.assertEqual(self.execute()['reason'],'TRADING_SESSION');self.assertFalse(self.p.state(a['account_id'])['positions'])
    def test_migration_preserves_full_ledger_and_projection(self):
        # A separate pre-upgrade store, without any catalog, reproduces startup.
        other=self.store.child('old');repo=AccountRepository(other);engine=AccountEngine(repo);a=engine.create({'account_type':'LIVE_SHADOW','initial_capital':200000,'policy':policy()},'TEST')
        with repo.transaction(a['account_id']) as db:before=(repo.events(db),repo.projection(db))
        p=PortfolioService(engine,self.quotes,namespace='TEST',clock=lambda:self.now);p2=PortfolioService(AccountEngine(AccountRepository(other)),self.quotes,namespace='TEST',clock=lambda:self.now)
        self.assertEqual(p.binding()['account_id'],a['account_id']);self.assertEqual(p2.binding(),p.binding());self.assertEqual(p.catalog()[0]['origin'],'MIGRATED_LIVE')
        with repo.transaction(a['account_id']) as db:self.assertEqual(before,(repo.events(db),repo.projection(db)))
    def test_delete_interrupt_recovery_and_no_shared_deletion(self):
        a=self.create();self.bind(a);path=self.p.engine.repository.path(a['account_id']);unknown=path.parent/'unknown.txt';unknown.write_text('manual material')
        with self.assertRaises(AccountError):self.p.delete(a['account_id'],{'confirmed':True})
        self.assertIsNone(self.p.binding()['account_id']);self.assertTrue(path.exists());self.assertFalse(self.p.catalog());unknown.unlink()
        p2=self.service();p2.delete(a['account_id'],{'confirmed':True});self.assertFalse(path.parent.exists())
    def test_api_boundaries_no_advanced_or_fund_correction(self):
        a=self.create();i=a['account_id'];self.assertEqual(self.router.route('GET','/api/accounts/'+i+'/ledger')[0],404)
        self.assertEqual(self.router.route('POST','/api/accounts/'+i+'/reconcile',{'mode':'MANUAL_CORRECTION','correction':{'cash_delta':1}})[0],409)
        self.assertFalse(self.router.accepts_put('/api/accounts/'+i+'/policy'));self.assertTrue(self.router.accepts_put('/api/accounts/execution-binding'))

class PortfolioPipelineRaces(ShadowDrill):
    def test_switch_during_ai_saved_opinion_no_execution(self):
        b=self.p.create({'name':'B','idempotency_key':'B','initial_capital':200000,'policy':policy(ai_execution_mode='AUTO_SHADOW_EXECUTION')})
        self.provider.callback=lambda:self.p.bind({'account_id':b['account_id'],'binding_version':self.p.binding()['binding_version']})
        op=self.auto();self.assertEqual(self.a.runtime.portfolio_outcome(op['advisory_id'])['reason'],'ACCOUNT_BINDING_CHANGED');self.assertTrue(self.a.opinions.input(op['input_id']));self.assertFalse(self.p.engine.state(self.id)['executions']);self.assertFalse(self.p.engine.state(b['account_id'])['executions'])
    def test_delete_during_ai_saves_opinion_without_resurrection(self):
        self.provider.callback=lambda:self.p.delete(self.id,{'confirmed':True})
        op=self.auto();self.assertEqual(self.a.runtime.portfolio_outcome(op['advisory_id'])['reason'],'ACCOUNT_BINDING_CHANGED');self.assertFalse(self.repo.path(self.id).exists());self.assertIsNotNone(self.a.latest('bj920161'))
    def test_pause_during_ai_preserves_opinion_blocks_buy(self):
        def pause():
            state=self.p.engine.state(self.id)
            self.p.settings(self.id,{'new_risk_paused':True,'account_state_version':state['account_state_version']})
        self.provider.callback=pause
        op=self.auto();self.assertEqual(self.a.runtime.portfolio_outcome(op['advisory_id'])['reason'],'NEW_RISK_PAUSED');self.assertFalse(self.p.engine.state(self.id)['positions'])

    def test_unbound_ai_still_succeeds(self):
        self.p.bind({'account_id':None,'binding_version':self.p.binding()['binding_version']});op=self.auto();self.assertEqual(self.a.runtime.portfolio_outcome(op['advisory_id'])['reason'],'NO_EXECUTION_ACCOUNT');self.assertFalse(self.p.engine.state(self.id)['executions'])

if __name__=='__main__':
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (UserPortfolios,PortfolioPipelineRaces))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():Path('docs/account_7_11_tests.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())
