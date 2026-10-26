"""market_data_agent CLI parsing must not depend on python-dotenv."""
from pathlib import Path
import contextlib, io, subprocess, sys, types, unittest
from unittest.mock import patch
import market_data_agent

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / 'market_data_agent.py'
BLOCK_DOTENV = r'''
import builtins, runpy, sys
real = builtins.__import__
def blocked(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'dotenv' or (isinstance(name, str) and name.startswith('dotenv.')):
        raise ImportError('simulated missing python-dotenv')
    return real(name, globals, locals, fromlist, level)
builtins.__import__ = blocked
target = sys.argv[1]
sys.argv = [target, *sys.argv[2:]]
runpy.run_path(target, run_name='__main__')
'''


class MarketDataAgentCliTests(unittest.TestCase):
    def run_blocked(self, *args):
        return subprocess.run(
            [sys.executable, '-c', BLOCK_DOTENV, str(AGENT), *args],
            cwd=ROOT, capture_output=True, text=True)

    def test_help_exits_zero_when_dotenv_cannot_be_imported(self):
        result = self.run_blocked('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--data-root', result.stdout)
        self.assertIn('--check', result.stdout)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('dotenv', result.stderr)

    def test_parse_errors_exit_two_when_dotenv_cannot_be_imported(self):
        missing = self.run_blocked()
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertIn('--data-root', missing.stderr)
        self.assertNotIn('Traceback', missing.stderr)
        invalid = self.run_blocked('--data-root', '/tmp/tradinglab-agent-cli', '--source', 'NOPE')
        self.assertEqual(invalid.returncode, 2, invalid.stderr)
        self.assertIn('--source', invalid.stderr)
        self.assertNotIn('Traceback', invalid.stderr)

    def test_missing_dotenv_still_fails_before_business(self):
        result = self.run_blocked('--data-root', '/tmp/tradinglab-agent-cli', '--check')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('dotenv', result.stderr)
        self.assertNotIn('data_root', result.stdout)

    def test_env_load_contract_unchanged_and_before_business(self):
        order = []
        expected = Path(market_data_agent.__file__).resolve().parent / '.env'

        def configure_logging():
            order.append('logging')

        def load_dotenv(*args, **kwargs):
            order.append(('dotenv', args, kwargs))

        def node_path():
            order.append('business')
            return 'node'

        fake = types.ModuleType('dotenv')
        fake.load_dotenv = load_dotenv
        output = io.StringIO()
        with patch('shared.logging.configure_logging', configure_logging), \
             patch.dict(sys.modules, {'dotenv': fake}), \
             patch.object(market_data_agent, 'node_path', node_path), \
             contextlib.redirect_stdout(output):
            code = market_data_agent.main(['--data-root', '/tmp/tradinglab-agent-cli', '--check', '--source', 'TEST'])
        self.assertEqual(code, 0)
        self.assertIn('/tmp/tradinglab-agent-cli', output.getvalue())
        self.assertEqual(order[0], 'logging')
        kind, args, kwargs = order[1]
        self.assertEqual(kind, 'dotenv')
        self.assertEqual(args, (expected,))
        self.assertEqual(kwargs, {'override': False})
        self.assertEqual(order[2], 'business')


if __name__ == '__main__':
    unittest.main()
