"""Four-module product boundaries, retained accounts and preserved market algorithms."""
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.request import urlopen
from urllib.error import HTTPError
from app.shell.server import make_server
from tests.agent_auto_fixture import AgentAutoFixture
from tests.account_fixture import policy

ROOT=Path(__file__).resolve().parents[1]


class ProductConvergenceTests(unittest.TestCase):
    def test_four_pages_retired_routes_and_no_product_imports(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            fixture=AgentAutoFixture(Path(tmp));app=fixture.app
            server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                self.assertEqual([m.id for m in app.registry.modules],['live','data_observation','account','system'])
                base=f'http://127.0.0.1:{server.server_port}'
                for route in ('/live','/data-observation','/account','/system','/assets/forms.css','/assets/account.js','/assets/live.js'):
                    with urlopen(base+route) as response:self.assertEqual(response.status,200)
                with urlopen(base+'/data-observation') as response:
                    html=response.read().decode()
                for retired in ('source-handoff','source-import','formal-capability','href="/decisions"'):
                    self.assertNotIn(retired,html)
                observation=next(r for r in app.routers if type(r).__name__=='ObservationRouter')
                self.assertFalse(observation.accepts_post('/api/data-observation/formal'))
                for route in ('/learning','/research','/decisions','/replay','/simulation','/api/learning/cases','/api/replay/sessions','/api/simulation/datasets','/api/live/decisions','/api/live/ack','/assets/formal.js'):
                    with self.assertRaises(HTTPError) as caught:urlopen(base+route)
                    self.assertEqual(caught.exception.code,404,route)
                forbidden=('app.learning','app.research','app.decisions','app.replay','engines.learning','engines.decisions','engines.replay','engines.live.simulation','adapters.legacy')
                self.assertFalse([name for name in sys.modules if name.startswith(forbidden)])
                self.assertFalse(hasattr(app.live_loop,'v2b'))
                self.assertFalse(hasattr(fixture.agent,'formal'))
                self.assertFalse(fixture.provider.calls)
            finally:server.shutdown();server.server_close();thread.join();fixture.close()

    def test_retained_historical_account_reads_without_old_owner(self):
        from engines.account.retained import preserve,read
        from contracts.account.portfolio import AccountError
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            f=AgentAutoFixture(Path(tmp))
            try:
                account=f.p.engine.create({'account_type':'REPLAY_SANDBOX','context_id':'old-session','initial_capital':10000,'policy':policy()},'TEST')
                identity=account['account_id'];before=f.p.engine.ledger(identity)
                evidence={'origin':{'source':'TEST','symbol':'bj920161','date':'2026-09-09'},'cases':[]}
                preserve(f.p.engine.repository,identity,evidence)
                self.assertEqual(read(f.p.engine.repository,identity),evidence)
                # Retained evidence remains Owner-readable; retired accounts exit product APIs.
                self.assertEqual(f.p.engine.state(identity)['account_id'],identity)
                with self.assertRaises(AccountError):f.p.state(identity)
                self.assertNotIn(identity,[a['account_id'] for a in f.p.catalog()])
                self.assertEqual(f.p.engine.ledger(identity),before)
                with self.assertRaises(AccountError):f.p.create({'account_type':'REPLAY_SANDBOX','context_id':'new','initial_capital':10000,'policy':policy()})
                with self.assertRaises(AccountError):f.p.submit(identity,{'symbol':'bj920161'})
            finally:f.close()

    def test_provider_configuration_and_sdk_import_no_legacy_execution(self):
        from adapters.ai.config import ConfigManager
        from adapters.ai.advisory import AdvisoryProvider
        from adapters.ai.providers import PROVIDER_REGISTRY
        self.assertEqual(set(PROVIDER_REGISTRY),{'deepseek','openai'})
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            root=Path(tmp);(root/'config').mkdir()
            (root/'config/ai.yaml').write_bytes((ROOT/'config/ai.yaml').read_bytes())
            config=ConfigManager(root,root/'config/ai.yaml')
            self.assertEqual(config.provider_config('deepseek')['model'],AdvisoryProvider(root).catalog()['default_model'])
            self.assertFalse((root/'legacy').exists())
        code="from adapters.ai.providers.deepseek_provider import DeepSeekProvider; from adapters.ai.providers.openai_provider import OpenAIProvider; from adapters.ai.worker import safe_exception_details; import sys; assert not any(k.startswith('coordinator') for k in sys.modules)"
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_market_calculation_functions_match_audited_bodies(self):
        source=(ROOT/'engines/live/market_agent/native_core.mjs').read_text(encoding='utf-8')
        manifest=json.loads((ROOT/'engines/live/market_agent/source_manifest.json').read_text(encoding='utf-8'))
        for name in ('buildTrackerRow','backfillTrackerMetrics','samePeriodVolumeStats','computeRuntimeWindowFields','collectRuntimeStockFields','trackerDeltaRows','trackerRowsWithEventDetails'):
            start=re.search(r'^    (?:async )?function '+name+r'\(',source,re.M)
            end=re.search(r'^    }\s*$',source[start.end():],re.M)
            body=source[start.start():start.end()+end.end()].rstrip()
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),manifest['functions'][name],name)
        self.assertNotIn('function applyDecisionAck(',source)
        self.assertNotIn('function buildAiHandoffSnapshot(',source)

    def test_runtime_source_has_no_retired_imports(self):
        prefixes=('app.learning','app.research','app.decisions','app.replay','engines.learning','engines.decisions','engines.replay','engines.live.simulation','contracts.training','contracts.replay','adapters.legacy')
        for base in ('app','engines','adapters','bridges','contracts','shared'):
            for path in (ROOT/base).rglob('*.py'):
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                    names=[node.module or ''] if isinstance(node,ast.ImportFrom) else [x.name for x in node.names] if isinstance(node,ast.Import) else []
                    self.assertFalse([n for n in names if n.startswith(prefixes)],str(path))
        for removed in ('bridges/v2b_worker.py','adapters/legacy_source_probe.py','contracts/account/replay.py'):
            self.assertFalse((ROOT/removed).exists())
