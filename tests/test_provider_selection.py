"""Provider selection contracts; every generation in this suite is Fake."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch,Mock
from threading import Event
from concurrent.futures import ThreadPoolExecutor
import json,tempfile,time,unittest
import httpx,jsonschema
from openai import OpenAI
from adapters.ai.advisory import AdvisoryProvider
from adapters.ai.capabilities import resolve,freeze,strict_schema,restore_optional,check_response,MODELS
from adapters.ai.providers.openai_provider import OpenAIProvider
from adapters.ai.providers.deepseek_provider import DeepSeekProvider
from adapters.ai.request_guard import RequestGuard,RequestGuardError
from app.system.ai_configuration import AIConfiguration
from shared.config import ScopedStore
from contracts.live.bridge import BridgeError
from adapters.ai.errors import CoordinatorError
from engines.history.service import PROMPT,SCHEMA

ROOT=Path(__file__).resolve().parents[1]
class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='provider-selection-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.provider=AdvisoryProvider(ROOT)
        self.owner=AIConfiguration(ScopedStore(self.root/'system',boundary=self.root),self.provider,
            {'provider':'deepseek','model':'deepseek-v4-pro','reasoning_effort':'low'})
    def test_migration_no_reset_idempotent_restart(self):
        a=self.owner.status();self.assertEqual(a['default']['reasoning_effort'],'low')
        b=self.owner.save(a['selection']);self.assertEqual(a['revision'],b['revision'])
        again=AIConfiguration(ScopedStore(self.root/'system',boundary=self.root),self.provider,{'provider':'openai'})
        self.assertEqual(again.resolve(),self.owner.resolve())
    def test_capability_unknown_draft_and_no_generation(self):
        with patch.object(self.provider,'analyze_history') as call:
            self.owner.save({'provider':'openai','model':'unknown-model','draft':True})
            self.assertEqual(self.owner.read('draft')['status'],'UNKNOWN_CAPABILITY')
            with self.assertRaises(BridgeError):self.owner.save({'provider':'openai','model':'unknown-model'})
            self.owner.save({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'medium'})
            call.assert_not_called()
    def test_provider_capabilities_and_endpoint_key_binding(self):
        c=self.provider.connections()
        with self.assertRaises(BridgeError):resolve({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'max'},c)
        bad=deepcopy(c);bad['openai']['api_key_env']='DEEPSEEK_API_KEY'
        with self.assertRaises(BridgeError):resolve({'provider':'openai','model':'gpt-5.4-mini'},bad)
        bad=deepcopy(c);bad['openai']['base_url']='https://untrusted.example'
        with self.assertRaises(BridgeError):resolve({'provider':'openai','model':'gpt-5.4-mini'},bad)
    def test_freeze_snapshot_and_semantic_output_identity(self):
        a=freeze(self.owner.resolve(),PROMPT,SCHEMA)
        self.owner.save({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'medium'})
        self.assertEqual(a['provider'],'deepseek');self.assertEqual(a['api_key_env'],'DEEPSEEK_API_KEY')
        b=freeze(self.owner.resolve(),PROMPT,SCHEMA)
        self.owner.save({'max_output_tokens':3200});c=freeze(self.owner.resolve(),PROMPT,SCHEMA)
        self.assertNotEqual(b['analysis_signature'],c['analysis_signature'])
        self.assertEqual(a,freeze(resolve(a,{'deepseek':a})|{'config_revision':a['config_revision'],'configuration_origin':a['configuration_origin']},PROMPT,SCHEMA))
    def test_strict_schema_no_invented_portfolio_values(self):
        schema=json.loads((ROOT/'contracts/live/advisory_opinion_1.0.json').read_text())
        wire=strict_schema(schema)
        self.assertEqual(set(wire['required']),set(wire['properties']))
        self.assertIn('anyOf',wire['properties']['game_state'])
        from tests.support.provider import analysis
        value=analysis();value['portfolio_plan']=None
        value['previous_hypothesis_review'].update({k:None for k in schema['properties']['previous_hypothesis_review']['properties'] if k not in ('status','reason')})
        jsonschema.validate(value,wire)
        restored=restore_optional(value,schema);jsonschema.validate(restored,schema)
        self.assertNotIn('portfolio_plan',restored)
        restored['portfolio_plan']={'portfolio_action':'OPEN','reason':'unknown','target_weight':None}
        restored=restore_optional(restored,schema);self.assertNotIn('target_weight',restored['portfolio_plan'])
    def client(self,p,reply,status=200):
        calls=[]
        def handle(r):calls.append(r);return httpx.Response(status,json=reply,headers={'x-request-id':'test-request'})
        client=OpenAI(api_key='FAKE-'+p,base_url='https://api.openai.com/v1' if p=='openai' else 'https://api.deepseek.com',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        self.addCleanup(client.close);return client,calls
    def response(self,**kw):
        return {'id':'r-test','object':'response','created_at':1,'model':'test','status':'completed',
            'output':[{'type':'message','id':'m','role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps({k:'测试' for k in SCHEMA['required']},ensure_ascii=False),'annotations':[]}]}],**kw}
    def test_native_requests_and_unknown_usage(self):
        for p,klass,effort in [('deepseek',DeepSeekProvider,'low'),('openai',OpenAIProvider,'medium')]:
            with self.subTest(p=p),patch.dict('os.environ',{'DEEPSEEK_API_KEY':'FAKE-deepseek','OPENAI_API_KEY':'FAKE-openai'}):
                c,calls=self.client(p,self.response());cfg=resolve({'provider':p,'model':next(iter(MODELS[p])),'reasoning_effort':effort},self.provider.connections())
                out=klass(cfg,prompt=PROMPT,output_schema=SCHEMA,client=c).analyze_event({'fact':'TEST'})
                sent=json.loads(calls[0].content);self.assertEqual(sent['reasoning'],{'effort':effort});self.assertNotIn('tools',sent)
                self.assertEqual(calls[0].headers['authorization'],'Bearer FAKE-'+p)
                self.assertIsNone(out['usage_records'][0]['input_tokens'])
                if p=='openai':self.assertTrue(sent['text']['format']['strict']);self.assertEqual(sent['max_output_tokens'],8192)
                else:self.assertNotIn('max_output_tokens',sent)
    def test_refusal_truncation_empty_invalid_no_success(self):
        variants=[({'status':'incomplete'},'OUTPUT_TRUNCATED'),({'output':[{'type':'message','id':'m','role':'assistant','content':[{'type':'refusal','refusal':'no'}]}]},'PROVIDER_REFUSAL'),({'output':[]},'INVALID_RESPONSE')]
        for v,code in variants:
            with self.subTest(code=code),patch.dict('os.environ',{'OPENAI_API_KEY':'FAKE'}):
                c,calls=self.client('openai',self.response(**v));cfg=self.owner.resolve({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'none'})
                with self.assertRaises(CoordinatorError) as e:OpenAIProvider(cfg,prompt=PROMPT,output_schema=SCHEMA,client=c).analyze_event({})
                self.assertEqual(str(e.exception.code),code);self.assertFalse(e.exception.usage_records[-1]['success']);self.assertEqual(len(calls),1)
    def test_http_parameter_auth_no_retry(self):
        for status in (400,401,403,429,500):
            with self.subTest(status=status),patch.dict('os.environ',{'OPENAI_API_KEY':'FAKE'}):
                c,calls=self.client('openai',{'error':{'message':'model invalid parameter SECRET','type':'invalid_request_error','code':'bad'}},status)
                cfg=self.owner.resolve({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'none'})
                with self.assertRaises(CoordinatorError) as e:OpenAIProvider(cfg,prompt=PROMPT,output_schema=SCHEMA,client=c).analyze_event({})
                self.assertEqual(len(calls),1);self.assertNotIn('SECRET',str(e.exception));self.assertNotEqual(str(e.exception.code),'MODEL_INVALID')
    def test_actual_http_limits_and_model_context(self):
        meta={'target_input_tokens':32000,'model_context_tokens':20000,'model_max_output_tokens':2000,'token_count_method':'ESTIMATE','input_builder_version':'test'}
        r=httpx.Request('POST','https://api.openai.com/v1/responses',json={'input':'{}','max_output_tokens':4000})
        g=RequestGuard(meta,endpoint=('api.openai.com','/v1/responses'))
        with self.assertRaises(RequestGuardError):g.before(r)
        meta['model_context_tokens']=400000;g=RequestGuard(meta,endpoint=('api.openai.com','/v1/responses'))
        for _ in range(3):g.before(r)
        with self.assertRaises(RequestGuardError):g.before(r)
    def fixture(self):
        from tests.support.native import NativeFixture
        f=NativeFixture(self.root/'fixture');self.addCleanup(f.close)
        f.provider.catalog=lambda:self.provider.catalog()|{'providers':[{**p,'error':None} for p in self.provider.catalog()['providers']]}
        f.advisory.model_configuration=self.owner
        return f
    def test_stock_override_follow_default_does_not_change_auto(self):
        f=self.fixture();a=f.advisory
        a.save_settings({'symbol':'bj920161','provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'high'})
        self.assertEqual(a.effective('bj920161')['provider'],'openai');self.assertEqual(a.effective('sh688696')['provider'],'deepseek')
        a.save_settings({'symbol':'bj920161','follow_default':True})
        self.assertEqual(a.effective('bj920161')['provider'],'deepseek');self.assertEqual(f.provider.calls,[])
    def test_model_change_is_not_new_facts_force_is_explicit(self):
        f=self.fixture();f.append();a=f.advisory;first=a.analyze('bj920161');cursor=deepcopy(a.runtime.cursor(first['tracking_session_id']))
        self.owner.save({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'low'})
        with self.assertRaises(BridgeError) as e:a.analyze('bj920161')
        self.assertEqual(e.exception.code,'NO_NEW_ADVISORY_DATA');self.assertEqual(cursor,a.runtime.cursor(first['tracking_session_id']));self.assertEqual(len(f.provider.calls),1)
        second=a.analyze('bj920161',force=True);self.assertEqual(second['provider'],'openai');self.assertEqual(second['trigger_type'],'MANUAL_REANALYSIS')
    def test_running_and_queued_task_model_is_frozen(self):
        f=self.fixture();f.append();a=f.advisory;entered=Event();release=Event()
        def callback():entered.set();self.assertTrue(release.wait(10))
        f.provider.callback=callback
        with ThreadPoolExecutor(2) as pool:
            job=pool.submit(a.analyze,'bj920161');self.assertTrue(entered.wait(5))
            f.append();queued=a.analyze('bj920161');self.assertTrue(queued['queued'])
            self.owner.save({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'low'})
            release.set();first=job.result(10);self.assertEqual(first['provider'],'deepseek');self.assertTrue(first['effective_result'])
            for _ in range(100):
                if len(f.provider.calls)>=2:break
                time.sleep(.03)
            self.assertEqual(len(f.provider.calls),2)
            self.assertTrue(all(c['frozen']['model_config']['provider']=='deepseek' for c in f.provider.calls))
    def test_parallel_stock_selection_isolated(self):
        f=self.fixture();a=f.advisory
        a.save_settings({'symbol':'sh688696','provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'medium'})
        for s in f.members:f.append(s)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(a.analyze,f.members))
        self.assertEqual({r['provider'] for r in results},{'deepseek','openai'})
        for c in f.provider.calls:self.assertEqual(c['provider'],c['frozen']['model_config']['provider'])

    def test_explicit_new_model_reanalysis_queues_behind_old_model(self):
        f=self.fixture();f.append();a=f.advisory;entered=Event();release=Event()
        def callback():entered.set();self.assertTrue(release.wait(10))
        f.provider.callback=callback
        with ThreadPoolExecutor(2) as pool:
            job=pool.submit(a.analyze,'bj920161');self.assertTrue(entered.wait(5))
            self.owner.save({'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'medium'})
            normal=a.analyze('bj920161');self.assertTrue(normal['coalesced'])
            forced=a.analyze('bj920161',force=True);self.assertTrue(forced['queued']);self.assertFalse(forced.get('coalesced'))
            again=a.analyze('bj920161',force=True);self.assertEqual(again['request_id'],forced['request_id'])
            release.set();job.result(10)
            for _ in range(100):
                if len(f.provider.calls)>=2:break
                time.sleep(.03)
            self.assertEqual([c['provider'] for c in f.provider.calls],['deepseek','openai'])

class HistorySelectionTests(SelectionTests):
    # Explicitly select only the additional method when running this subclass.
    def test_history_overrides_dedup_and_registration(self):
        from tests.test_history import Adapter,Provider,rows
        from engines.history.bars import BarsEngine,TZ
        from engines.history.store import HistoryStore
        from engines.history.service import HistoricalAnalysis
        from engines.account.rules import TradingCalendar
        from datetime import datetime
        store=HistoryStore(self.root/'history');p=Provider();now=datetime(2026,9,25,16,tzinfo=TZ)
        bars=BarsEngine(store,Adapter(rows()),TradingCalendar(),lambda:now)
        service=HistoricalAnalysis(bars,store,p,lambda:{},'TEST');self.addCleanup(service.close);service.model_configuration=self.owner
        q={'symbol':'bj920161','end_date':'2026-09-23','period':'DAY','volume_period':'DAY','samples':10,'limit':31,'adjustment':'NONE'}
        def finish(identity,selection=None):
            j=service.submit({**q,'request_id':identity,**({'model_selection':selection} if selection else {})})
            for _ in range(200):
                j=store.job(j['id'])
                if j['status'] not in ('RUNNING','QUEUED'):break
                time.sleep(.01)
            self.assertEqual(j['status'],'SUCCEEDED',j.get('error'));return j
        a=finish('history-first');b=finish('history-repeat');self.assertEqual(a['id'],b['id'])
        self.owner.save(self.owner.read('default')['selection']);self.assertEqual(finish('history-save')['id'],a['id'])
        override={'provider':'openai','model':'gpt-5.4-mini','reasoning_effort':'high'}
        c=finish('history-override',override);self.assertNotEqual(a['id'],c['id']);self.assertEqual(c['opinion']['provider'],'openai')
        self.assertEqual(self.owner.resolve()['provider'],'deepseek');self.assertIsNone(p.inputs[-1]['portfolio_context'])
        self.assertEqual(c['input']['model_config'],c['opinion']['model_config'])
        self.assertEqual(finish('history-override-again',override)['id'],c['id'])
        # Upgrade a pre-snapshot success without inventing its old output budget or re-billing.
        service.model_configuration=None;service.settings=lambda:{'provider':'deepseek','model':'deepseek-v4-pro','reasoning_effort':'low'}
        q['symbol']='sh688601';legacy=finish('legacy-before-upgrade');count=len(p.inputs)
        service.model_configuration=self.owner
        reused=service.submit({**q,'request_id':'legacy-after-upgrade'})
        self.assertEqual(reused['id'],legacy['id']);self.assertTrue(reused['model_configuration_unverified'])
        self.assertEqual(len(p.inputs),count)
