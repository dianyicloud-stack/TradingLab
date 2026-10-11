"""Synthetic market + Fake AI; real queues, policies, account ledger and recovery."""
from pathlib import Path
from datetime import datetime,timedelta
import tempfile,unittest,json
from unittest.mock import patch
from shared.config import ScopedStore
from tests.support.facts import ClockedFacts as SimulationLiveFactSource
from engines.live.advisory import AdvisoryService
from engines.live.advisory_repository import AdvisoryRuntimeRepository,AdvisoryOpinionRepository
from engines.account.engine import AccountEngine
from engines.account.ledger import AccountRepository
from engines.account.quotes import QuoteService
from app.account.portfolio import PortfolioService
from tests.account_fixture import policy
from tests.support.provider import PlanProvider

ROOT=Path(__file__).resolve().parents[1]
RESULTS={}
class ShadowDrill(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='shadow-drill-');self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.store=ScopedStore(root,boundary=root)
        self.now=datetime.fromisoformat('2026-09-18T10:00:00+08:00');self.price=10;self.seq=0
        clock_patch=patch('engines.account.ledger.stamp',side_effect=lambda:self.now.isoformat())
        clock_patch.start();self.addCleanup(clock_patch.stop)
        self.source=SimulationLiveFactSource({'dataset_id':'SYNTHETIC-DRILL','source_session_date':'2026-09-18','symbols':['bj920161'],'sessions':[],'facts':[]},lambda:self.now)
        self.repo=AccountRepository(self.store.child('accounts'));self.engine=AccountEngine(self.repo)
        self.p=PortfolioService(self.engine,QuoteService(self.source),namespace='TEST',clock=lambda:self.now.isoformat())
        self.provider=PlanProvider();self.provider.callback=lambda:setattr(self,'now',self.now+timedelta(seconds=2))
        self.a=AdvisoryService(self.source,AdvisoryRuntimeRepository(self.store.child('runtime')),AdvisoryOpinionRepository(self.store.child('opinions')),self.provider,source='TEST',clock=lambda:self.now)
        self.addCleanup(lambda:self.a._auto_pool.shutdown(wait=True))
        self.a.portfolio_context=lambda s:self.p.context(s,refresh=False);self.a.portfolio_result=self.p.on_advisory
        self.a.market_is_open=self.engine.rules.calendar.is_open
        self.a.save_settings({'auto_ai_mode':'ALL_EVENTS','auto_event_types':['NEW_HIGH'],'debounce_seconds':3})
        self.account=self.p.create({'name':'演练组合','idempotency_key':'primary','account_type':'LIVE_SHADOW','initial_capital':200000,'policy':policy(ai_execution_mode='AUTO_SHADOW_EXECUTION')})
        self.id=self.account['account_id']
        self.p.bind({'account_id':self.id,'binding_version':self.p.binding()['binding_version']})
    def auto(self,action='OPEN',weight=.25,expect_opinion=True):
        day=self.now.date().isoformat();sid='TS-'+day.replace('-','')+'-bj920161-01'
        ds=self.source.dataset
        if ds['source_session_date']!=day:ds['facts']=[];self.seq=0
        ds['source_session_date']=day;ds['sessions']=[{'tracking_session_id':sid,'symbol':'bj920161','name':'合成演练股票','session_date':day}]
        self.now+=timedelta(seconds=10);self.seq+=1;stamp=self.now.isoformat()
        obs={'price':self.price,'timestamp':stamp,'requested_time':self.now.strftime('%H:%M:%S'),'vwap':self.price,'volume':1000*self.seq}
        event={'symbol':'bj920161','tracking_session_id':sid,'event_seq':self.seq,'timestamp':stamp,'type':'NEW_HIGH','severity':'IMPORTANT'}
        for kind,payload in [('OBSERVATION',obs),('EVENT',event)]:ds['facts'].append({'kind':kind,'timestamp':stamp,'available_at':stamp,'symbol':'bj920161','tracking_session_id':sid,'payload':payload})
        self.provider.action=action;self.provider.target=weight
        self.a.ingest();self.a.poll_auto();self.now+=timedelta(seconds=4);self.a.poll_auto()
        opinion=self.a.latest('bj920161')
        if not expect_opinion:return opinion
        self.assertIsNotNone(opinion)
        self.assertEqual(opinion['trigger_type'],'AUTO_EVENT')
        task=self.a.runtime.latest_request(sid);self.assertEqual(task['status'],'COMPLETED')
        return opinion
    def record(self,name,op):
        s=self.p.state(self.id,refresh=False);out=self.a.runtime.portfolio_outcome(op['advisory_id'])
        RESULTS[name]={'outcome':out,'cash':s['cash'],'quantity':s['positions'].get('bj920161',{}).get('qty',0),
            'realized_pnl':s['realized_pnl'],'rule':self.engine.rules.rule('bj920161'),'opinion_available':op['generated_at']}
        return s,out
    def test_qualified_open_and_repeat(self):
        op=self.auto();s,out=self.record('qualified_open',op)
        self.assertEqual(out['status'],'EXECUTED');self.assertGreater(out['executed_qty'],0)
        self.assertAlmostEqual(s['cash'],200000-out['gross_amount']-out['fees']['total'],places=2)
        self.assertGreaterEqual(datetime.fromisoformat(out['market_time']),datetime.fromisoformat(op['generated_at']))
        kinds={e['event_type'] for e in self.engine.ledger(self.id)}
        self.assertTrue({'INTENT_CREATED','ORDER_CREATED','FILL_RECORDED'}<=kinds)
        ledger=self.engine.ledger(self.id)
        order=next(e for e in ledger if e['event_type']=='ORDER_CREATED')
        fill=next(e for e in ledger if e['event_type']=='FILL_RECORDED')
        self.assertGreaterEqual(datetime.fromisoformat(fill['created_at']),datetime.fromisoformat(order['created_at']))
        self.assertGreaterEqual(datetime.fromisoformat(order['created_at']),datetime.fromisoformat(op['generated_at']))
        frozen=self.a.opinions.input(op['input_id']);duplicate=self.p.on_advisory(op,frozen)
        self.assertTrue(duplicate['duplicate']);self.a.ingest();self.a.poll_auto()
        self.assertEqual(len(self.provider.calls),1);self.assertEqual(len(self.engine.state(self.id)['executions']),1)
        RESULTS['duplicate']={'duplicate':True,'executions':1,'cash':s['cash'],'quantity':s['positions']['bj920161']['qty']}
    def test_advisory_only(self):
        self.engine.policy(self.id,policy());op=self.auto();s,out=self.record('advisory_only',op)
        self.assertEqual(out['status'],'WAITING_HUMAN_CONFIRMATION');self.assertEqual(s['cash'],200000);self.assertFalse(s['executions'])
    def test_funds_insufficient(self):
        # Distinct creation instants select the new account, not a tied UUID order.
        self.now+=timedelta(seconds=1)
        account=self.p.create({'name':'小资金','idempotency_key':'small','account_type':'LIVE_SHADOW','initial_capital':100,'policy':policy(ai_execution_mode='AUTO_SHADOW_EXECUTION')});self.id=account['account_id']
        self.p.bind({'account_id':self.id,'binding_version':self.p.binding()['binding_version']})
        op=self.auto();s,out=self.record('insufficient_funds',op)
        self.assertEqual(out['executed_qty'],0);self.assertTrue(out['reason']);self.assertEqual(s['cash'],100)
    def test_missing_evidence_no_execution(self):
        # Real source declares no Observation: native completeness gate, no fabricated facts.
        self.source.native_facts_only=True
        original=self.source.advisory_facts
        self.source.advisory_facts=lambda s:{**original(s),'observations':[]}
        # Auto correctly refuses missing evidence before provider; manual can save a view but cannot trade.
        self.assertIsNone(self.auto(expect_opinion=False))
        self.assertEqual(len(self.provider.calls),0)
        self.assertFalse(self.engine.state(self.id)['executions'])
        frozen=self.a.freeze('bj920161','AUTO_EVENT');reason=self.a.eligibility(frozen,self.a.effective('bj920161'))['blockers']
        self.assertIn('LIMITED_EVIDENCE',reason)
        RESULTS['insufficient_evidence']={'reasons':reason,'executions':0,'cash':200000,'quantity':0}
    def test_sell_cross_day_restart(self):
        self.auto();locked=self.auto('EXIT',0);s,out=self.record('t1_blocked',locked)
        self.assertEqual(out['reason'],'T1_LOCK');self.assertEqual(out['executed_qty'],0)
        before=self.engine.ledger(self.id);self.p.engine=AccountEngine(self.repo)
        self.assertEqual(before,self.p.engine.ledger(self.id))
        self.now=datetime.fromisoformat('2026-09-21T10:00:00+08:00');self.price=11
        sold=self.auto('EXIT',0);s,out=self.record('next_day_sell',sold)
        self.assertEqual(out['status'],'EXECUTED');self.assertFalse(s['positions']);self.assertGreater(out['fees']['stamp_duty'],0)
        self.assertGreaterEqual(datetime.fromisoformat(out['market_time']),datetime.fromisoformat(sold['generated_at']))
        restored=AccountEngine(self.repo);self.assertEqual(restored.state(self.id),self.p.engine.state(self.id))
        duplicate=self.p.on_advisory(sold,self.a.opinions.input(sold['input_id']));self.assertTrue(duplicate['duplicate'])
        RESULTS['restart']={'ledger_equal':True,'duplicate_sell':True,'cash':s['cash'],'quantity':0}

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ShadowDrill))
    if result.wasSuccessful():
        (ROOT/'docs/shadow_drill_results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())
