"""Regression: an occupied market-source lock cannot queue display reads."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import RLock
from threading import Thread,Event
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
import tempfile,json,time
import socket,struct
from pathlib import Path
from app.live.router import LiveRouter
from bridges.market_agent import AgentClient,AgentFactBridge
from bridges.active_market_source import ActiveMarketSource
from shared.logging.timing import RequestTimings,stage


class RuntimeReadIsolationTests(unittest.TestCase):
    def test_page_load_connection_burst_can_wait_for_accept(self):
        from app.shell.server import make_server
        server=make_server(SimpleNamespace(routers=(),runtime=None),0);connections=[];thread=None
        try:
            # A cold page and polling may connect before the accept loop gets
            # its next timeslice. None of those legitimate connections is lost.
            for _ in range(12):
                connections.append(socket.create_connection(('127.0.0.1',server.server_port),timeout=2))
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            for connection in connections:
                connection.sendall(b'GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n')
                self.assertIn(b'200 OK',connection.recv(4096))
        finally:
            for connection in connections:connection.close()
            if thread:server.shutdown();thread.join(3)
            server.server_close()

    def test_source_lock_does_not_block_unrelated_routes_static_or_settings(self):
        workspace=SimpleNamespace(lock=RLock(),identity=lambda:{'source_generation':'one'})
        loop=SimpleNamespace(workspace=workspace,source='TEST',advisory=SimpleNamespace(catalog=lambda:{'global':{}}))
        router=LiveRouter(loop)
        for path in ('/live','/data-observation','/assets/live.js','/assets/live.css',
                     '/assets/data-observation.js','/api/data-observation/state','/api/live/advisory/settings'):
            with self.subTest(path=path):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    workspace.lock.acquire()
                    future=pool.submit(router.route,'GET',path,{'view':'display'})
                    try:
                        result=future.result(timeout=.3)
                    except TimeoutError:
                        self.fail('Display request waits on market-source lock: '+path)
                    finally:workspace.lock.release()

    def test_stocks_cached_read_remains_available_during_source_work(self):
        workspace=SimpleNamespace(lock=RLock(),identity=lambda:{'source_generation':'one'})
        runtime=SimpleNamespace(retired_sessions=lambda:set())
        router=LiveRouter(SimpleNamespace(workspace=workspace,source='TEST',advisory=SimpleNamespace(runtime=runtime)))
        router.read_model=Mock();router.read_model.read.return_value={'source_generation':'one','advisory_cards':[]}
        with ThreadPoolExecutor(max_workers=1) as pool:
            with workspace.lock:
                result=pool.submit(router.route,'GET','/api/live/stocks',{'view':'display'}).result(timeout=.3)
        self.assertEqual(result[0],200)

    def test_scope_reuses_one_owner_response_and_never_retains_between_reads(self):
        client=AgentClient(None,'TEST');client.request=Mock(side_effect=[{'source':'TEST','version':1},{'source':'TEST','version':2}])
        with client.snapshot_scope():
            first=client.query();first['version']=999
            with client.snapshot_scope():self.assertEqual(client.query()['version'],1)
            self.assertEqual(client.request.call_count,1)
        self.assertEqual(client.query()['version'],2)
        self.assertEqual(client.request.call_count,2)

    def test_projection_scope_is_copy_safe_and_exception_does_not_leak(self):
        client=AgentClient(None,'TEST');client.request=Mock(return_value={'source':'TEST','sessions':[],'facts':[]})
        bridge=AgentFactBridge(client)
        with self.assertRaises(ValueError):
            with bridge.snapshot_scope():
                bridge.fact_snapshot().append({'fake':'caller change'})
                self.assertEqual(bridge.fact_snapshot(),[])
                raise ValueError('test failure')
        self.assertEqual(bridge.fact_snapshot(),[]);self.assertEqual(client.request.call_count,2)

    def test_fixed_source_generation_cannot_be_changed_by_switch_command(self):
        client=AgentClient(None,'TEST');client.request=Mock(return_value={'source':'TEST','sessions':[],'facts':[]})
        source=ActiveMarketSource(AgentFactBridge(client),{'source_generation':'stable'})
        with source.read_scope():
            source.sessions();self.assertFalse(hasattr(source,'activate'))
            self.assertEqual(source.identity()['source_generation'],'stable')
        self.assertEqual(source.mode,'MARKET_AGENT')

    def test_timings_are_bounded_and_do_not_contain_business_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder=RequestTimings(Path(tmp)/'read.jsonl')
            for _ in range(150):
                with recorder.request('/api/live/stocks','GET'):
                    with stage('serialization'):pass
            state=recorder.snapshot();self.assertEqual(state['active'],0);self.assertEqual(len(state['recent']),128)
            self.assertEqual(state['completed'],150);self.assertEqual(state['peak'],1)
            self.assertIn('serialization',state['recent'][0]['stages']);recorder.close()
            body=(Path(tmp)/'read.jsonl').read_text();self.assertNotIn('Authorization',body);self.assertNotIn('payload',body)

    def test_live_shell_never_invokes_source_health(self):
        from app.live.module import create_module
        from app.shell.registry import ModuleRegistry
        from app.shell.render import render_page
        health=Mock(side_effect=AssertionError('Agent fetch from HTML'))
        module=create_module(health);self.assertIn(b'live.js',render_page(ModuleRegistry([module]),module));health.assert_not_called()

    def test_client_disconnect_work_finishes_and_is_reported_without_retry(self):
        from app.shell.server import make_server
        from app.shell.registry import ModuleRegistry
        entered=Event();release=Event()
        class Delay:
            def route(self,method,path,payload):
                entered.set();release.wait(1);return 200,{'ok':True},None
        timings=RequestTimings(enabled=True)
        app=SimpleNamespace(routers=(Delay(),),registry=ModuleRegistry())
        server=make_server(app,0,diagnostics=timings);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            connection=socket.create_connection(('127.0.0.1',server.server_port))
            connection.sendall(b'GET /test/read HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
            self.assertTrue(entered.wait(1));connection.setsockopt(socket.SOL_SOCKET,socket.SO_LINGER,struct.pack('hh',1,0));connection.close()
            self.assertEqual(timings.snapshot()['active'],1) # cancellation is not server completion
            release.set()
            for _ in range(100):
                if timings.snapshot()['completed']:break
                time.sleep(.01)
            report=timings.snapshot();self.assertEqual(report['active'],0);self.assertEqual(report['completed'],1)
            self.assertTrue(report['recent'][0]['disconnected'])
        finally:release.set();server.shutdown();server.server_close();thread.join(2)
