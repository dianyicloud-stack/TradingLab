"""Unified account invariants with isolated TEST ledgers; no production writes."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contracts.account.portfolio import AccountError
from engines.account.engine import AccountEngine
from engines.account.ledger import AccountRepository
from engines.account.rules import TradingCalendar,MarketRuleService
from shared.config import ScopedStore
from tests.account_fixture import policy,quote


class AccountCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.repo=AccountRepository(ScopedStore(root/'accounts',boundary=root));self.engine=AccountEngine(self.repo)
        self.account=self.create();self.a=self.account['account_id'];self.n=0

    def create(self,kind='LIVE_SHADOW',**overrides):
        return self.engine.create({'account_type':kind,'context_id':None if kind=='LIVE_SHADOW' else 'test-session',
            'initial_capital':500000,'policy':policy(**overrides)},'TEST')

    def trade(self,action='OPEN',qty=1000,source='LIVE_MANUAL',symbol='bj920161',time='2026-09-10T10:00:00+08:00',account=None,**extra):
        self.n+=1
        intent={'symbol':symbol,'portfolio_action':action,'qty':qty,'source':source,'source_ref':str(self.n),'reason':'TEST ONLY',**extra}
        return self.engine.submit(account or self.a,intent,quote(symbol,10,time),time)


class AccountLedgerTests(AccountCase):
    def test_explicit_capital(self):self.assertEqual(self.account['cash'],500000)
    def test_default_advisory_mode(self):self.assertEqual(self.account['policy']['ai_execution_mode'],'ADVISORY_ONLY')
    def test_missing_capital_rejected(self):
        with self.assertRaises(AccountError):self.engine.create({'account_type':'LIVE_SHADOW','policy':policy()})
    def test_generation_preserves_ledger(self):
        self.trade();before=self.engine.ledger(self.a)
        newer=self.engine.create({'account_type':'LIVE_SHADOW','initial_capital':100000,'policy':policy(),'parent_account_id':self.a},'TEST')
        self.assertEqual(newer['account_generation'],2);self.assertEqual(self.engine.ledger(self.a),before)
    def test_context_isolation(self):
        replay=self.create('REPLAY_SANDBOX');sim=self.create('SIMULATION_SANDBOX');self.trade(account=replay['account_id'],source='LEARNING');self.trade(account=sim['account_id'],source='SIMULATION')
        self.assertEqual(self.engine.state(self.a)['cash'],500000);self.assertNotEqual(self.repo.path(self.a),self.repo.path(replay['account_id']))
    def test_cross_context_source_denied(self):
        with self.assertRaises(AccountError):self.trade(source='REPLAY')
    def test_intent_not_direct_projection(self):
        e=self.trade();events=self.engine.ledger(self.a)
        self.assertTrue(any(x['event_type']=='INTENT_CREATED' for x in events));self.assertTrue(any(x['event_type']=='FILL_RECORDED' for x in events))
        self.assertGreater(e['executed_qty'],0)
    def test_immutable_facts(self):
        self.trade()
        with self.repo.transaction(self.a) as db:
            for sql in ('DELETE FROM ledger','UPDATE ledger SET payload=\'{}\''):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
    def test_restart_persists(self):
        self.trade();other=AccountEngine(self.repo);self.assertEqual(other.state(self.a),self.engine.state(self.a))
    def test_no_sizing_no_default(self):
        result=self.trade(qty=None);self.assertEqual(result['reason'],'NEEDS_SIZING');self.assertEqual(result['executed_qty'],0)
    def test_fee_slippage_separate(self):
        e=self.trade(signal_price=9.5);self.assertEqual(e['reference_price'],10);self.assertGreater(e['execution_price'],10);self.assertGreater(e['fees']['total'],0)
    def test_target_repeat_no_double_add(self):
        a=self.trade(qty=None,target_weight=.25);b=self.trade('ADD',qty=None,target_weight=.25)
        self.assertGreater(a['executed_qty'],0);self.assertEqual(b['executed_qty'],0)
    def test_idempotent(self):
        a=self.trade(source_ref='same');b=self.trade(source_ref='same');self.assertEqual(a['execution_id'],b['execution_id']);self.assertTrue(b['duplicate'])
    def test_ai_needs_confirm(self):self.assertEqual(self.trade(source='LIVE_AI_AUTO')['reason'],'HUMAN_CONFIRMATION_REQUIRED')
    def test_auto_policy(self):
        self.engine.policy(self.a,policy(ai_execution_mode='AUTO_SHADOW_EXECUTION'));self.assertGreater(self.trade(source='LIVE_AI_AUTO')['executed_qty'],0)
    def test_off_policy(self):
        self.engine.policy(self.a,policy(ai_execution_mode='OFF'));self.assertEqual(self.trade(source='LIVE_AI_CONFIRMED')['reason'],'AI_EXECUTION_OFF')
    def test_manual_protected(self):
        self.trade();self.assertEqual(self.engine.state(self.a)['lots'][0]['ownership'],'MANUAL_PROTECTED')
    def test_ai_cannot_sell_manual(self):
        self.trade();e=self.trade('EXIT',source='LIVE_AI_CONFIRMED',time='2026-09-11T10:00:00+08:00');self.assertEqual(e['reason'],'MANUAL_PROTECTED')
    def test_manual_add_reduce_exit(self):
        self.trade();self.trade('ADD');e=self.trade('REDUCE',qty=500,time='2026-09-11T10:00:00+08:00');self.assertEqual(e['executed_qty'],500)
        e=self.trade('EXIT',time='2026-09-11T10:01:00+08:00');self.assertEqual(e['executed_qty'],1500)
    def test_t1_locked(self):
        self.trade();e=self.trade('EXIT');self.assertEqual(e['status'],'DEFERRED');self.assertEqual(e['reason'],'T1_LOCK')
    def test_partial_t1(self):
        self.trade();self.trade('ADD',qty=2000,time='2026-09-11T10:00:00+08:00');e=self.trade('REDUCE',qty=1500,time='2026-09-11T10:01:00+08:00')
        self.assertEqual((e['executed_qty'],e['blocked_qty'],e['reason']),(1000,500,'T1_LOCK'))
    def test_deferred_next_day_reevaluation(self):
        self.trade();self.trade('EXIT');s=self.engine.state(self.a,'2026-09-11T10:00:00+08:00');self.assertEqual(s['executions'][-1]['reevaluation_status'],'READY_FOR_REEVALUATION');self.assertEqual(s['positions']['bj920161']['qty'],1000)
    def test_weekend_holiday(self):
        c=TradingCalendar();self.assertEqual(c.next_day('2026-09-11'),'2026-09-14');self.assertEqual(c.next_day('2026-09-30'),'2026-10-08')
    def test_limit_per_symbol(self):self.assertEqual(self.trade(qty=30000)['reason'],'POSITION_LIMIT')
    def test_max_open_positions(self):
        self.engine.policy(self.a,policy(max_open_positions=1));self.trade();self.assertEqual(self.trade(symbol='sh600000')['reason'],'MAX_OPEN_POSITIONS')
    def test_daily_new_limit(self):
        self.engine.policy(self.a,policy(max_new_positions_per_day=1));self.trade();self.assertEqual(self.trade(symbol='sz000001')['reason'],'MAX_NEW_POSITIONS_PER_DAY')
    def test_add_not_new_symbol(self):
        self.trade();self.trade('ADD');self.assertEqual(self.engine.state(self.a)['new_positions_today'],1)
    def test_daily_exposure(self):
        self.engine.policy(self.a,policy(max_new_exposure_per_day_pct=.01));e=self.trade(qty=1000);self.assertEqual(e['reason'],'MAX_NEW_EXPOSURE_PER_DAY')
    def test_total_exposure(self):
        self.engine.policy(self.a,policy(max_total_exposure_pct=.01));self.assertEqual(self.trade()['reason'],'MAX_TOTAL_EXPOSURE')
    def test_cash_reserve(self):
        self.engine.policy(self.a,policy(minimum_cash_reserve_pct=.99));self.assertEqual(self.trade()['reason'],'MINIMUM_CASH_RESERVE')
    def test_concurrent_symbols_no_overspend(self):
        self.engine.policy(self.a,policy(max_position_weight_per_symbol=1,max_total_exposure_pct=1,max_new_exposure_per_day_pct=1,minimum_cash_reserve_pct=0))
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda s:self.trade(qty=40000,symbol=s),['bj920161','sh600000']))
        self.assertGreaterEqual(self.engine.state(self.a)['cash'],0);self.assertLess(sum(x['gross_amount'] for x in results),500000)
    def test_concurrent_same_id(self):
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.trade(source_ref='same'),range(2)))
        self.assertEqual(results[0]['execution_id'],results[1]['execution_id'])
    def test_void_keeps_history(self):
        e=self.trade();before=len(self.engine.ledger(self.a));s=self.engine.void(self.a,e['execution_id'],'mistake','TEST');self.assertEqual(s['cash'],500000);self.assertEqual(s['executions'][0]['status'],'VOIDED');self.assertGreater(len(self.engine.ledger(self.a)),before)
    def test_void_invalidates_dependent_sell(self):
        e=self.trade();sell=self.trade('EXIT',time='2026-09-11T10:00:00+08:00');s=self.engine.void(self.a,e['execution_id'],'mistake','TEST');self.assertIn(sell['execution_id'],s['invalid_executions'])
    def drift(self):
        with self.repo.transaction(self.a) as db:
            p=self.repo.projection(db);p['cash']+=1;self.repo.save_projection(db,p)
    def test_drift_detected(self):
        self.drift();self.assertEqual(self.engine.state(self.a)['reconciliation_status'],'RECONCILIATION_REQUIRED')
    def test_drift_blocks_auto(self):
        self.engine.policy(self.a,policy(ai_execution_mode='AUTO_SHADOW_EXECUTION'));self.drift();self.assertEqual(self.trade(source='LIVE_AI_AUTO')['reason'],'RECONCILIATION_REQUIRED')
    def test_unknown_delta_recorded(self):
        self.drift();self.engine.state(self.a);self.assertIn('UNKNOWN_DELTA',[e['event_type'] for e in self.engine.ledger(self.a)])
    def test_reconcile_rebuild(self):
        self.drift();s=self.engine.reconcile(self.a,'REBUILD_FROM_LEDGER','ignore external projection','TEST');self.assertEqual(s['cash'],500000);self.assertEqual(s['reconciliation_status'],'RECONCILED')
    def test_manual_correction_protected(self):
        self.drift();s=self.engine.reconcile(self.a,'MANUAL_CORRECTION','accept explicit delta','TEST',{'cash_delta':-1000,'lot':{'symbol':'bj920161','qty':100,'unit_cost':10,'trade_date':'2026-09-10'}})
        self.assertEqual(s['lots'][0]['ownership'],'MANUAL_PROTECTED')
    def test_ownership_explicit_transfer(self):
        self.trade();lot=self.engine.state(self.a)['lots'][0];self.engine.ownership(self.a,lot['lot_id'],'AI_MANAGED','explicit consent','TEST');e=self.trade('EXIT',source='LIVE_AI_CONFIRMED',time='2026-09-11T10:00:00+08:00');self.assertEqual(e['executed_qty'],1000)
    def test_valuation(self):
        self.trade();time='2026-09-10T10:01:00+08:00';s=self.engine.observe(self.a,[quote(price=12,time=time)],time);self.assertEqual(s['market_value'],12000);self.assertGreater(s['unrealized_pnl'],0)
    def test_future_quote_denied(self):
        with self.assertRaises(AccountError):self.engine.observe(self.a,[quote(time='2026-09-11T10:00:00+08:00')],'2026-09-10T10:00:00+08:00')
    def test_stale_quote_deferred(self):
        e=self.engine.submit(self.a,{'symbol':'bj920161','portfolio_action':'OPEN','qty':100,'source':'LIVE_MANUAL'},quote(),'2026-09-10T10:06:00+08:00');self.assertEqual(e['reason'],'STALE_QUOTE')
    def test_missing_quote_deferred(self):
        e=self.engine.submit(self.a,{'symbol':'bj920161','portfolio_action':'OPEN','qty':100,'source':'LIVE_MANUAL'},None,'2026-09-10T10:00:00+08:00');self.assertEqual(e['reason'],'QUOTE_UNAVAILABLE')
    def test_market_rules(self):
        rules=MarketRuleService();self.assertEqual(rules.round_qty('bj920161',2339),2339);self.assertEqual(rules.round_qty('sh600000',2339),2300);self.assertEqual(rules.round_qty('sh688696',201),201);self.assertEqual(rules.round_qty('sz000001',99),0)
    def test_attribution(self):
        self.trade();self.trade('EXIT',time='2026-09-11T10:00:00+08:00');self.assertIn('LIVE_MANUAL',self.engine.state(self.a)['attribution'])
    def test_context_feedback(self):
        self.trade();ctx=self.engine.context(self.a,'bj920161');self.assertTrue(ctx['position_exists']);self.assertEqual(ctx['recent_actions'][-1]['source'],'LIVE_MANUAL')
    def test_ai_auto_then_confirm_same_advisory(self):
        self.engine.policy(self.a,policy(ai_execution_mode='AUTO_SHADOW_EXECUTION'))
        a=self.trade(source='LIVE_AI_AUTO',source_ref='ADV-same');b=self.trade(source='LIVE_AI_CONFIRMED',source_ref='ADV-same')
        self.assertEqual(a['execution_id'],b['execution_id']);self.assertTrue(b['duplicate'])
    def test_daily_budget_resets_only_on_new_trade_day(self):
        self.engine.policy(self.a,policy(max_new_positions_per_day=1));self.trade();next_day='2026-09-11T10:00:00+08:00'
        self.engine.observe(self.a,[quote(time=next_day)],next_day)
        result=self.trade(symbol='sz000001',time=next_day);self.assertGreater(result['executed_qty'],0)
    def test_portfolio_changed_event(self):
        self.trade();event=self.engine.ledger(self.a)[-1]
        self.assertEqual(event['event_type'],'PORTFOLIO_STATE_CHANGED');self.assertEqual(event['position_qty'],1000);self.assertEqual(event['available_qty'],0)
    def test_price_limit_defers(self):
        q=quote();q['limit_up']=10
        e=self.engine.submit(self.a,{'symbol':'bj920161','portfolio_action':'OPEN','qty':100,'source':'LIVE_MANUAL'},q,q['quote_time'])
        self.assertEqual(e['reason'],'PRICE_LIMIT');self.assertEqual(e['executed_qty'],0)
    def test_replace_cannot_destroy_ledger(self):
        with self.repo.transaction(self.a) as db,self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT OR REPLACE INTO ledger SELECT * FROM ledger')
    def test_ambiguous_sizing_rejected(self):
        with self.assertRaises(AccountError):self.trade(qty=100,target_weight=.25)


if __name__=='__main__':unittest.main()
