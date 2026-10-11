"""Offline evidence and actual SDK transport checks. No external calls."""
from copy import deepcopy
from pathlib import Path
import json,sqlite3,tempfile,unittest
from contextlib import closing
import httpx
from openai import OpenAI
from engines.live.evidence import build,summarize,tabulate,encoded,VERSION
from adapters.ai.request_guard import RequestGuard,sanitized_error,RequestGuardError
from engines.live.provider_request_repository import ProviderRequestRepository
from contracts.live.bridge import BridgeError

class EvidenceTests(unittest.TestCase):
    def frozen(self,n=500):
        from datetime import datetime,timedelta,timezone
        start=datetime(2026,9,17,1,30,tzinfo=timezone.utc)
        rows=[]
        for i in range(n):
            t=(start+timedelta(seconds=i*5)).isoformat()
            rows.append({'symbol':'bj920161','tracking_session_id':'test-1','timestamp':t,'available_at':t,
                'source_format':'V2A_RUNTIME_SNAPSHOT_V1','fields':{'price':20+(i%17)/100,'vwap':20.08,'cumulative_volume':1000+i},
                'price':20+(i%17)/100,'vwap':20.08,'quality':'LIMITED','missing_evidence':['INDUSTRY']})
        return {'input_id':'test-input','input_hash':'test-hash','symbol':'bj920161','tracking_session_id':'test-1',
            'created_at':(start+timedelta(days=1)).isoformat(),'incremental_evidence':{'events':[],'observations':rows},
            'context_evidence':{'events':[],'observations':[]},'live_observation':rows[-1],'current_state':rows[-1]}
    def test_deterministic_and_original_unchanged(self):
        f=self.frozen();original=deepcopy(f)
        self.assertEqual(build(f,'prompt',{}),build(f,'prompt',{}));self.assertEqual(f,original)
    def test_growth_does_not_send_full_snapshot_objects(self):
        for n in (200,1000,2000):
            e,m=build(self.frozen(n),'p',{},target=100000)
            self.assertEqual(e['snapshot_path']['count'],n)
            self.assertNotIn('observations',e);self.assertLess(m['evidence_bytes'],len(encoded(self.frozen(n)).encode())*.55)
    def test_duplicate_facts_removed(self):
        f=self.frozen();f['incremental_evidence']['observations']*=2
        self.assertEqual(build(f,'p',{})[0]['snapshot_path']['count'],500)
    def test_future_rejected(self):
        f=self.frozen();f['incremental_evidence']['observations'][0]['available_at']='2099-01-01T00:00:00+00:00'
        with self.assertRaises(BridgeError):build(f,'p',{})
    def test_other_symbol_rejected(self):
        f=self.frozen();f['incremental_evidence']['observations'][0]['symbol']='sh688601'
        with self.assertRaises(BridgeError):build(f,'p',{})
    def test_budget_failure_is_explicit(self):
        with self.assertRaises(BridgeError) as caught:build(self.frozen(),'p',{},target=1)
        self.assertEqual(caught.exception.code,'INPUT_BUDGET')
    def test_extrema_and_crossing_order_quality(self):
        f=self.frozen();r=f['incremental_evidence']['observations'];s=summarize(r,[],15)
        self.assertTrue(s['crossings']);self.assertEqual([x[0] for x in s['crossings']],sorted(x[0] for x in s['crossings']))
        self.assertEqual(s['intervals'][0]['metrics']['price'][2][1],20)
        self.assertEqual(s['intervals'][0]['metrics']['price'][3][1],20.16)
        self.assertEqual(s['quality_runs'][0][1]['missing_evidence'],['INDUSTRY'])
        self.assertFalse(s['native'])
    def test_column_encoding_missing_null_and_quality(self):
        value=tabulate([{'x':None,'quality':'BAD'},{'quality':'BAD'}])
        self.assertEqual(value['common']['/quality'],'BAD');self.assertEqual(value['missing'],[[],[0]])
    def test_formal_events_never_dropped(self):
        f=self.frozen();f['incremental_evidence']['events']=[{'timestamp':f['created_at'],'event_seq':i,'type':'ACTUAL'} for i in range(45)]
        f['incremental_evidence']['observations'].append({'timestamp':f['created_at'],'observation_kind':'FORMAL','quality':'LIMITED'})
        e,m=build(f,'p',{},target=100000)
        self.assertEqual(m['source_counts']['events'],45);self.assertEqual(m['source_counts']['observations'],1)

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.meta={'target_input_tokens':32768,'token_count_method':'ESTIMATE','input_builder_version':VERSION}
        self.path=str(Path(self.tmp.name)/'budget.db')
    def req(self,n=1):return httpx.Request('POST','https://api.deepseek.com/responses',json={'model':'deepseek-v4-pro','input':json.dumps({'n':n})})
    def test_shared_actual_allowance(self):
        for i in range(3):RequestGuard(self.meta,budget_path=self.path).before(self.req(i))
        with self.assertRaises(RequestGuardError) as e:RequestGuard(self.meta,budget_path=self.path).before(self.req(4))
        self.assertEqual(e.exception.code,'HTTP_ATTEMPT_BUDGET_EXHAUSTED')
    def test_same_400_not_reissued(self):
        g=RequestGuard(self.meta,budget_path=self.path);g.before(self.req());g.after(httpx.Response(400,json={'error':{'message':'invalid parameter'}}))
        with self.assertRaises(RequestGuardError):RequestGuard(self.meta,budget_path=self.path).before(self.req())
    def test_sdk_final_body_and_error_redaction(self):
        g=RequestGuard(self.meta,budget_path=self.path)
        client=OpenAI(api_key='TEST-ONLY',base_url='https://api.deepseek.com',max_retries=0,http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r:httpx.Response(400,json={'error':{'message':'maximum context length 1000 tokens; input SECRET_ACCOUNT sk-12345','code':'context_length_exceeded','type':'invalid_request_error','param':'input'}},headers={'x-request-id':'test-123'})),
            event_hooks={'request':[g.before],'response':[g.after]}))
        with self.assertRaises(Exception):client.responses.create(model='deepseek-v4-pro',input='{}',reasoning={'effort':'low'})
        client.close();d=g.diagnostics()
        self.assertEqual(d['provider_attempt_count'],1);self.assertEqual(d['http_attempts'][0]['upstream_error']['reason'],'INPUT_LENGTH_REJECTED')
        self.assertNotIn('SECRET_ACCOUNT',str(d));self.assertNotIn('sk-12345',str(d));self.assertNotIn('request_body',d['http_attempts'][0])
        self.assertEqual(d['http_attempts'][0]['request_body_bytes'],len(g.records[0]['request_body'].encode()))
    def test_parameter_is_not_length(self):
        self.assertEqual(sanitized_error({'error':{'message':'unsupported parameter reasoning'}})['reason'],'REQUEST_PARAMETER_REJECTED')
    def test_actual_budget_before_send(self):
        g=RequestGuard({**self.meta,'target_input_tokens':1},budget_path=self.path)
        with self.assertRaises(RequestGuardError):g.before(self.req())
        self.assertFalse(Path(self.path).exists());self.assertFalse(g.records)
    def test_request_records_immutable(self):
        r=ProviderRequestRepository(Path(self.tmp.name)/'audit');r.append('test','HTTP_REQUEST',{'request_body':'{}'})
        with closing(sqlite3.connect(r.path)) as db, db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM records')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE records SET kind='changed'")

if __name__=='__main__':unittest.main()
