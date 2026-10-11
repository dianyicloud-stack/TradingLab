"""Small deployment-only checks. No production data/services/Provider calls."""
from pathlib import Path
from contextlib import contextmanager
import hashlib,json,os,sqlite3,sys,tempfile,unittest
from unittest.mock import patch
WORK=Path(__file__).resolve().parents[1];RELEASE=WORK/'TradingLabPortable'
sys.path.insert(0,str(RELEASE));sys.path.insert(0,str(RELEASE/'TradingLab'))
import portable_control as control
import migration

class PortableTests(unittest.TestCase):
    def test_runtime_is_bundled_and_native_extensions_load(self):
        import jiter,pydantic_core,rpds,yaml,openai,ssl,sqlite3
        self.assertEqual(sys.version_info[:3],(3,12,14))
        self.assertEqual(Path(sys.base_prefix).resolve(),(RELEASE/'runtime/python').resolve())
        self.assertTrue(all(Path(p).is_relative_to(RELEASE/'runtime/python') for p in sys.path if 'site-packages' in p))
    def test_manifest_covers_runtime_source_and_no_private_files(self):
        manifest=control.load(RELEASE/'runtime/files.json')
        self.assertIn('runtime/python/python312.dll',manifest);self.assertIn('runtime/node/node.exe',manifest)
        self.assertNotIn('TradingLab/.env',manifest);self.assertFalse(any(x.startswith('TradingLab/data/') for x in manifest))
    def test_incomplete_migration_cannot_start(self):
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            root=Path(tmp);(root/'MIGRATION_INCOMPLETE').write_text('incomplete')
            with patch.object(control,'ROOT',root),self.assertRaisesRegex(control.Blocked,'迁移尚未完成'):control.configure()
    def test_outside_path_rejected(self):
        with self.assertRaises(control.Blocked):control.safe_path(WORK.parent)
    def test_path_binding_keeps_business_budget_configuration(self):
        previous=Path.cwd()
        try:
            with patch.dict(os.environ,{'TRADING_LAB_DATA_ROOT':'Z:/old','TRADING_LAB_AI_INPUT_TOKEN_TARGET':'32768'}):
                control.configure()
                self.assertEqual(os.environ['TRADING_LAB_AI_INPUT_TOKEN_TARGET'],'32768')
                self.assertEqual(Path(os.environ['TRADING_LAB_DATA_ROOT']),RELEASE/'TradingLab/data')
        finally:os.chdir(previous)
    def test_old_venv_cannot_override_bundled_runtime(self):
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            root=Path(tmp);(root/'.venv').mkdir()
            with patch.object(control,'CORE',root),self.assertRaisesRegex(control.Blocked,'旧 .venv'):
                control.preflight({'web_port':8765})
    def test_live_foreign_descriptor_not_adopted(self):
        from adapters.runtime_platform import identity
        record={**identity(),'project':str(WORK.parent),'data_root':str(WORK.parent/'data')}
        with self.assertRaisesRegex(control.Blocked,'其他目录实例'):control.owned(record,'web')
    def test_migration_never_overwrites_existing_target(self):
        with self.assertRaisesRegex(control.Blocked,'不存在的新目录'):
            migration.migrate(WORK/'source/core',WORK/'source/agent',RELEASE,True)
    def test_missing_owner_lease_not_assumed_stopped(self):
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            with self.assertRaisesRegex(control.Blocked,'租约'):
                with migration.stopped_lease(Path(tmp)):pass
    def test_migration_cannot_copy_while_owner_lease_active(self):
        from adapters.runtime_lease import runtime_lease
        with tempfile.TemporaryDirectory(dir=WORK) as tmp:
            root=Path(tmp)
            with runtime_lease(root),self.assertRaisesRegex(control.Blocked,'租约'):
                with migration.stopped_lease(root):pass
    def test_source_code_changes_match_reviewed_history_and_current_lock(self):
        source=control.load(WORK/'source-before.json');different=[]
        for rel,sha in source.items():
            if control.digest(RELEASE/'TradingLab'/rel)!=sha:different.append(rel)
        self.assertEqual(sorted(different),['adapters/runtime_platform.py','adapters/telegram.py','app/system/notifications.py','docs/FROZEN_BASELINES.md','docs/frozen_baselines.json'])
        current=control.load(WORK/'source-lock.json')['business']
        self.assertEqual(control.load(RELEASE/'runtime/source-original.json'),current)
        self.assertTrue(all(control.digest(RELEASE/'TradingLab'/rel)==sha for rel,sha in current.items()))
    def test_old_health_burst_fixture_with_current_app_contract(self):
        # This does not weaken the old 200 assertion; supplies its missing app.runtime field.
        from app.shell.server import make_server
        from types import SimpleNamespace
        from threading import Thread
        import socket
        server=make_server(SimpleNamespace(routers=(),runtime=None),0);connections=[]
        try:
            for _ in range(12):connections.append(socket.create_connection(('127.0.0.1',server.server_port),timeout=2))
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            for connection in connections:
                connection.sendall(b'GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n')
                self.assertIn(b'200 OK',connection.recv(4096))
        finally:
            for connection in connections:connection.close()
            server.shutdown();server.server_close();thread.join(3)
    def test_windows_process_table_decodes_this_unicode_path(self):
        from adapters.runtime_platform import process_table,identity
        me=identity();entry=next(row for row in process_table() if row['ProcessId']==me['pid'])
        self.assertEqual(Path(entry['ExecutablePath']).resolve(),Path(me['executable']).resolve())
    def test_windows_process_table_preserves_unicode_command(self):
        import subprocess
        from adapters.runtime_platform import process_table
        with tempfile.TemporaryDirectory(dir=WORK,prefix='中文 进程-') as tmp:
            program=Path(tmp)/'测试进程.py'
            program.write_text("import sys;print('ready',flush=True);sys.stdin.read()",encoding='utf-8')
            child=subprocess.Popen([sys.executable,'-I','-B',str(program)],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
            try:
                self.assertEqual(child.stdout.readline().strip(),b'ready')
                entry=next(row for row in process_table() if row['ProcessId']==child.pid)
                self.assertIn(str(program),entry['CommandLine'])
            finally:child.stdin.close();child.wait(10);child.stdout.close()

if __name__=='__main__':unittest.main()
