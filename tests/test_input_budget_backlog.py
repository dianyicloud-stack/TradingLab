"""Production-size evidence tests. Private task captures stay outside test source."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
import importlib.util,json,tempfile,unittest
from unittest.mock import patch
import httpx
from contracts.live.bridge import BridgeError
from engines.live.advisory import PROMPT
from engines.live.evidence import build,encoded,digest,tabulate,compact_offsets,VERSION
from adapters.ai.request_guard import RequestGuard
from tests import test_ai_evidence as primitives

ROOT=Path(__file__).resolve().parents[1];CAPTURE=ROOT/'artifacts/input_budget_20260918'
SCHEMA=json.loads((ROOT/'contracts/live/advisory_opinion_1.0.json').read_text(encoding='utf-8'))

def decode(table):
    result=[]
    for row,missing in zip(table['rows'],table.get('missing',[[]]*len(table['rows']))):
        flat={**table.get('common',{}),**{key:row[i] for i,key in enumerate(table['columns']) if i not in missing}}
        for alias,key in table.get('aliases',{}).items():
            if key in flat:flat[alias]=deepcopy(flat[key])
        value={}
        for path,v in flat.items():
            parts=[x.replace('~1','/').replace('~0','~') for x in path[1:].split('/')];node=value
            for part in parts[:-1]:node=node.setdefault(part,{})
            node[parts[-1]]=deepcopy(v)
        result.append(value)
    return result

def sample(symbol,hydrate=True):
    frozen=json.loads((CAPTURE/'private'/f'{symbol}.json').read_text(encoding='utf-8'))['frozen']
    if hydrate:
        base=symbol.removesuffix('-later')
        recovery=json.loads((CAPTURE/'private'/f'{base}-baselines.json').read_text(encoding='utf-8'))
        assert not recovery['missing']
        frozen['comparison_observations']=recovery['observations']
        # Isolated derived input: the original persisted task is never edited.
        frozen['input_hash']=digest({k:v for k,v in frozen.items() if k not in ('input_id','input_hash')})
        frozen['input_id']='ADVIN-'+frozen['input_hash'][:32]
    return frozen

def old_builder():
    path=CAPTURE/'before/engines/live/evidence.py'
    spec=importlib.util.spec_from_file_location('budget_v2_snapshot',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class EvidenceCodecTests(unittest.TestCase):
    def test_lossless_aliases_null_missing_zero_false_and_escaped_paths(self):
        rows=[{'a':0,'b':0,'c':False,'n':None,'nested':{'x/y~':1}},
              {'a':False,'b':False,'c':0,'nested':{'x/y~':2}}]
        self.assertEqual(encoded(decode(tabulate(rows))),encoded(rows))
        self.assertEqual(tabulate(rows)['aliases']['/b'],'/a')
    def test_lossless_clock_runs_including_lunch_gap_and_fraction(self):
        offsets=list(range(0,3600,5))+list(range(9000,12600,5))+[12600.5,12601.25]
        p=compact_offsets(offsets);decoded=[p['first']]
        for count,delta in p['runs']:
            for _ in range(count):decoded.append(decoded[-1]+delta)
        self.assertEqual(decoded,offsets)
    def test_safe_refusal_retains_budget_diagnostics_and_never_spawns_provider(self):
        from adapters.ai.transport import ProviderTransport
        f=primitives.EvidenceTests().frozen(100)
        with patch.dict('os.environ',{'TRADING_LAB_AI_INPUT_TOKEN_TARGET':'1'}),patch('subprocess.run') as network:
            with self.assertRaises(BridgeError) as caught:ProviderTransport(ROOT).analyze(f,'low',{},PROMPT,SCHEMA,advisory_diagnostics=True)
        network.assert_not_called();self.assertEqual(caught.exception.code,'INPUT_BUDGET')
        self.assertEqual(len(caught.exception.failure_metadata['input_budget']['rounds']),4)
        self.assertEqual(caught.exception.failure_metadata['provider_attempt_count'],0)
    def test_zero_budget_is_not_silently_replaced(self):
        with self.assertRaises(BridgeError):build(primitives.EvidenceTests().frozen(),PROMPT,SCHEMA,target=0)

@unittest.skipUnless((CAPTURE/'capture.json').exists(),'private production captures required; portable codec tests still run')
class ProductionBacklogTests(unittest.TestCase):
    @contextmanager
    def service(self,symbols):
        from tests.support.native import NativeFixture
        with tempfile.TemporaryDirectory(prefix='budget-recovery-',dir=ROOT/'tests') as temp:
            fixture=NativeFixture(Path(temp));a=fixture.advisory;data={}
            try:
                fixture.now=datetime.fromisoformat('2026-09-18T14:55:30+08:00');a.market_is_open=lambda _:True
                for symbol in symbols:
                    frozen=sample(symbol);rows=frozen['incremental_evidence']['observations']+frozen['context_evidence']['observations']+frozen['comparison_observations']
                    rows=list({digest(r):r for r in rows}.values());rows.sort(key=lambda r:r['timestamp'])
                    events=list({r['event_seq']:r for r in frozen['incremental_evidence']['events']+frozen['context_evidence']['events']}.values())
                    formal=[r for r in rows if r.get('source_format')=='V2A_NATIVE_EXPORT_V1']
                    member={**frozen['source_session'],'symbol':symbol,'name':symbol,'tracking_session_id':frozen['tracking_session_id'],
                        'market_date':frozen['session_date'],'session_date':frozen['session_date'],'lifecycle':'ACTIVE',
                        'last_observation_time':rows[-1]['timestamp'],'latest_snapshot_time':rows[-1]['timestamp'],
                        'latest_structure_time':formal[-1]['timestamp'],'latest_complete_observation_time':formal[-1]['timestamp'],
                        'market_observed_at':rows[-1]['timestamp'],'source_event_max':max(e['event_seq'] for e in events)}
                    data[symbol]={'session':member,'observations':rows,'events':events,'current_state':rows[-1]}
                    prior=json.loads((CAPTURE/'private'/f'{symbol}-previous.json').read_text(encoding='utf-8'))
                    a.opinions.append(prior['frozen'],prior['opinion']);a.runtime.commit_success(prior['frozen'],prior['opinion'])
                class RecordedFacts:
                    native_facts_only=True
                    def advisory_facts(self,symbol):return deepcopy(data[symbol])
                    def sessions(self):return [deepcopy(d['session']) for d in data.values()]
                a.workspace=RecordedFacts();fixture.app.live_loop.workspace=a.workspace
                account=fixture.create('ADVISORY_ONLY');a.portfolio_context=lambda symbol:{'status':'NOT_INITIALIZED','ai_execution_mode':'ADVISORY_ONLY','test_account_id':account['account_id']}
                original=fixture.provider.analyze;fixture.budget_inputs=[]
                def budget_provider(frozen,provider,model,effort,prompt,schema):
                    e,m=build(frozen,prompt,schema,target=32768);fixture.budget_inputs.append((deepcopy(frozen),m))
                    return original(frozen,provider,model,effort,prompt,schema)
                fixture.provider.analyze=budget_provider
                yield fixture,a,data,account
            finally:fixture.close()

    def test_consecutive_provider_failure_then_live_chain_recovers_without_false_cursor_or_trade(self):
        with self.service(['bj920161']) as (f,a,data,account):
            sid=data['bj920161']['session']['tracking_session_id'];before=a.runtime.cursor(sid)
            ledger=f.p.engine.ledger(account['account_id']);provider=f.provider.analyze
            def fail(*args):
                build(args[0],args[4],args[5],target=32768)
                raise TimeoutError('TEST timeout')
            with patch.object(f.provider,'analyze',side_effect=fail):
                for _ in range(2):
                    with self.assertRaises(BridgeError):a.analyze('bj920161')
                    self.assertEqual(a.runtime.cursor(sid),before)
            opinion=a.analyze('bj920161')
            self.assertEqual(a.runtime.cursor(sid)['last_advisory_id'],opinion['advisory_id'])
            self.assertGreater(a.runtime.cursor(sid)['last_advised_event_seq'],before['last_advised_event_seq'])
            self.assertEqual(f.p.engine.ledger(account['account_id']),ledger)
            self.assertEqual(len(f.budget_inputs),1);self.assertTrue(f.budget_inputs[0][0]['comparison_observations'])
            self.assertIsNotNone(a.opinions.by_id(opinion['advisory_id']))

    def test_three_stock_live_chain_parallel_keeps_accounts_and_cursors_isolated(self):
        symbols=['bj920161','sh688601','sz300474']
        with self.service(symbols) as (f,a,data,account):
            ledger=f.p.engine.ledger(account['account_id'])
            with ThreadPoolExecutor(max_workers=3) as pool:opinions=list(pool.map(a.analyze,symbols))
            self.assertEqual([o['symbol'] for o in opinions],symbols)
            self.assertEqual(len(f.budget_inputs),3)
            for o in opinions:self.assertEqual(a.runtime.cursor(o['tracking_session_id'])['last_advisory_id'],o['advisory_id'])
            self.assertEqual(f.p.engine.ledger(account['account_id']),ledger)

    def test_two_exact_original_failures_and_original_success_control(self):
        old=old_builder()
        for symbol in ('bj920161','sh688601'):
            with self.subTest(symbol=symbol),self.assertRaises(BridgeError) as caught:old.build(sample(symbol,False),PROMPT,SCHEMA,target=32768)
            self.assertEqual(caught.exception.code,'INPUT_BUDGET')
        _,meta=old.build(sample('sz300474',False),PROMPT,SCHEMA,target=32768)
        self.assertEqual(meta['estimated_input_tokens'],14467)
    def test_all_three_same_asof_evidence_fit_with_actual_http_guard(self):
        records=json.loads((CAPTURE/'private/sz300474-provider.json').read_text(encoding='utf-8'))
        template=json.loads(next(r['payload']['request_body'] for r in records if r['kind']=='HTTP_REQUEST'))
        policy=json.loads(template['input'])['action_policy']
        for symbol in ('bj920161','sh688601','sz300474'):
            with self.subTest(symbol=symbol):
                frozen=sample(symbol);copy=deepcopy(frozen);e,m=build(frozen,PROMPT,SCHEMA,target=32768)
                self.assertEqual(frozen,copy);self.assertLessEqual(m['estimated_input_tokens'],32768)
                body={**template,'input':encoded({**e,'action_policy':policy})}
                guard=RequestGuard(m)
                guard.before(httpx.Request('POST','https://api.deepseek.com/responses',content=encoded(body).encode()))
                self.assertEqual(len(guard.records),1) # local boundary only; no transport is opened
    def test_formal_values_events_and_each_comparison_reference_roundtrip(self):
        for symbol in ('bj920161','sh688601'):
            frozen=sample(symbol);e,_=build(frozen,PROMPT,SCHEMA,target=32768)
            formal=[r for r in frozen['incremental_evidence']['observations'] if r.get('source_format')!='V2A_RUNTIME_SNAPSHOT_V1']
            self.assertEqual(encoded(decode(e['formal_observations'])),encoded(formal))
            self.assertEqual(encoded(decode(e['events'])),encoded(frozen['incremental_evidence']['events']))
            refs=decode(e['evidence_validation']['reference_table']);checks=decode(e['evidence_validation']['event_checks'])
            self.assertLess(len(refs),sum(len(c['evidence_refs']) for c in frozen['evidence_validation']['events']))
            for check,original in zip(checks,frozen['evidence_validation']['events']):
                restored=[{k:v for k,v in refs[i].items() if k!='observation_location'} for i in check['evidence_ref_indices']]
                self.assertEqual(restored,original['evidence_refs'])
                for i in check['evidence_ref_indices']:
                    ref=refs[i];loc=ref['observation_location'];row=decode(e[loc['table']])[loc['row']]
                    self.assertEqual(row['native_sha256'],ref['sha256']);self.assertIn('price',row)
    def test_missing_or_wrong_historical_reference_fails_before_provider(self):
        for mutate in ('missing','hash'):
            f=sample('bj920161')
            if mutate=='missing':f['comparison_observations']=[]
            else:f['comparison_observations'][0]['native_sha256']='wrong'
            with self.assertRaises(BridgeError) as caught:build(f,PROMPT,SCHEMA)
            self.assertEqual(caught.exception.code,'EVIDENCE_REFERENCE_MISSING')
    def test_actual_backlog_continued_to_1501_without_success_can_recover(self):
        initial=sample('sh688601');later=sample('sh688601-later')
        self.assertGreater(len(later['incremental_evidence']['observations']),len(initial['incremental_evidence']['observations']))
        self.assertEqual(later['previous_advisory']['advisory_id'],initial['previous_advisory']['advisory_id'])
        self.assertLessEqual(build(later,PROMPT,SCHEMA,target=32768)[1]['estimated_input_tokens'],32768)
    def test_high_frequency_growth_from_existing_production_scale(self):
        f=sample('bj920161');source=f['incremental_evidence']['observations'];snapshots=[r for r in source if r.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1']
        extra=[]
        for row in snapshots:
            r=deepcopy(row);stamp=(datetime.fromisoformat(r['timestamp'])+timedelta(seconds=1)).isoformat()
            for k in ('timestamp','market_observed_at','sampled_at','available_at'):r[k]=stamp
            r['field_times']={k:{'as_of':stamp} for k in r['field_times']};r['record_id']+='-TEST-DENSE';extra.append(r)
        source.extend(extra);source.sort(key=lambda r:r['timestamp'])
        f['input_frozen_at']=(datetime.fromisoformat(f['input_frozen_at'])+timedelta(seconds=5)).isoformat()
        e,m=build(f,PROMPT,SCHEMA,target=32768)
        self.assertEqual(e['snapshot_path']['count'],len(snapshots)*2);self.assertLessEqual(m['estimated_input_tokens'],32768)
    def test_summary_retains_every_referenced_time_extremum_crossing_and_quality_boundary(self):
        from engines.live.evidence import summarize
        frozen=sample('bj920161');e,m=build(frozen,PROMPT,SCHEMA)
        rows=[r for r in frozen['incremental_evidence']['observations'] if r.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1']
        original=summarize(rows,frozen['incremental_evidence']['events'],m['snapshot_interval_minutes']);projected=e['snapshot_path']
        for key in ('intervals','crossings','quality_runs','event_nearby_points','event_nearby_indices'):
            self.assertEqual(projected[key],original[key])
        offsets=projected['time_offsets_seconds'];self.assertEqual(offsets['encoding'],'indexed-offsets-v1')
        times=dict(offsets['pairs']);needed={0,len(rows)-1,*projected['event_nearby_indices']}
        for interval in projected['intervals']:
            needed.update(interval['range'])
            for values in interval['metrics'].values():needed.update(point[0] for point in values)
        needed.update(p[0] for p in projected['crossings']);needed.update(p[0] for p in projected['quality_runs'])
        for i in needed:self.assertEqual(times[i],original['time_offsets_seconds'][i])
    def test_auto_checks_link_to_the_same_full_validation_without_repeating_history(self):
        f=sample('sh688601-later');e,_=build(f,PROMPT,SCHEMA)
        original=f['evidence_validation']['events'];links=e['auto_qualification']['evidence_checks']['items']
        restored=[original[p['row']] if 'row' in p else p['inline'] for p in links]
        self.assertEqual(restored,f['auto_qualification']['evidence_checks'])
    def test_future_and_other_symbol_session_or_day_cannot_hide_in_compaction(self):
        for key,value in (('available_at','2099-01-01T00:00:00+00:00'),('symbol','sz000001'),('tracking_session_id','OTHER'),('session_date','2026-09-19')):
            f=sample('bj920161');f['comparison_observations'][0][key]=value
            with self.subTest(field=key),self.assertRaises(BridgeError):build(f,PROMPT,SCHEMA)
    def test_three_parallel_inputs_configuration_and_hash_are_independent(self):
        samples=[sample(s) for s in ('bj920161','sh688601','sz300474')]
        def run(pair):
            f,target=pair;return build(f,PROMPT,SCHEMA,target=target)
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,zip(samples,(32768,32768,20000))))
        self.assertEqual(len({m['evidence_sha256'] for _,m in results}),3)
        for f,(e,m),budget in zip(samples,results,(32768,32768,20000)):
            self.assertEqual(e['symbol'],f['symbol']);self.assertEqual(m['target_input_tokens'],budget)
            self.assertEqual(m['input_builder_version'],VERSION);self.assertEqual(m['evidence_sha256'],digest(e))
            self.assertEqual(build(f,PROMPT,SCHEMA,target=budget),(e,m))
    def test_overwhelming_required_events_still_refused_not_dropped(self):
        f=sample('sz300474');f['incremental_evidence']['events']=[{'event_seq':i,'timestamp':f['data_through_at'],'evidence':{'indispensable':'unique-'+str(i)*100}} for i in range(1000)]
        with self.assertRaises(BridgeError) as caught:build(f,PROMPT,SCHEMA,target=32768)
        self.assertEqual(caught.exception.code,'INPUT_BUDGET')
        self.assertEqual(caught.exception.budget_diagnostics['rounds'][-1]['source_counts']['events'],1000)
