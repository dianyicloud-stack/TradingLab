"""System process/file adapter. No market DB access or native algorithm ownership."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
from bridges.market_agent import AgentClient
from contracts.live.market_agent import AgentError
from engines.live.market_agent.service import node_path


class SourceLifecycle:
    def __init__(self, project, config):
        self.project = Path(project).resolve()
        self.root = Path(config['market_agent_root']).resolve()
        self.source = config['source']
        self.client = AgentClient(self.root, source=self.source)
        self.process = None

    def inspect(self):
        errors = []
        try:
            self.validate_paths()
        except AgentError as error:
            errors.append(error.code)
        try:
            node = node_path()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            node = None
            errors.append(getattr(error, 'code', 'NODE_RUNTIME_ERROR'))
        for name in ('market_data_agent.py', 'engines/live/market_agent/worker.mjs', 'engines/live/market_agent/native_core.mjs'):
            if not (self.project / name).is_file():
                errors.append('MISSING:' + name)
        parent = self.root
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        writable = parent.is_dir() and os.access(parent, os.W_OK)
        if not writable:
            errors.append('AGENT_ROOT_NOT_WRITABLE')
        agent = self.status()
        if agent['status'] == 'ERROR':
            errors.append(agent['error'])
        # Existing DB schema is checked by its owner, never by a System SQLite connection.
        if (self.root / 'market_agent.db').exists() and agent['status'] == 'STOPPED':
            schema = 'OWNER_CHECK_ON_STAGED_START'
        else:
            schema = agent.get('identity', {}).get('db_schema', 'NEW_DATABASE')
        return {'errors': errors, 'python': sys.executable, 'node': node, 'root': str(self.root),
            'root_exists': self.root.exists(), 'write_access': 'OS_ACCESS_CHECK' if writable else 'ERROR',
            'db_schema': schema, 'agent': agent}

    def validate_paths(self):
        root = self.root.resolve()
        if root != self.root:
            raise AgentError('AGENT_ROOT_CHANGED')
        if 'legacy' in [p.lower() for p in root.parts]:
            raise AgentError('AGENT_ROOT_REJECTED')
        if self.source == 'USER' and (root.is_relative_to(self.project) or self.project.is_relative_to(root)):
            raise AgentError('AGENT_DATA_ROOT_MUST_BE_SEPARATE')

    def query(self):
        value = self.client.query()
        identity = value.get('agent_identity', {})
        if Path(identity.get('root', '')).resolve() != self.root or Path(identity.get('project', '')).resolve() != self.project:
            raise AgentError('AGENT_INSTANCE_MISMATCH')
        if identity.get('db_schema') != '1.0':
            raise AgentError('AGENT_SCHEMA_MISMATCH')
        return value

    def status(self):
        try:
            value = self.query()
            return {'status': value['agent_state'], 'identity': value['agent_identity'], 'last_cycle_at': value.get('last_cycle_at'), 'errors': value.get('errors', [])}
        except AgentError as error:
            return {'status': 'STOPPED' if error.code in ('AGENT_UNAVAILABLE','AGENT_NOT_CONFIGURED') else 'ERROR', 'error': error.code}

    def write_record(self, name, value):
        if name != 'activation.json':
            raise AgentError('RECORD_NOT_ALLOWED')
        self.validate_paths()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        temp = path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)

    def start(self, paused=False):
        self.validate_paths()
        status = self.status()
        if status['status'] == 'ERROR':
            raise AgentError(status['error'])
        if 'identity' in status:
            return self.query()
        node_path()
        if self.source != 'USER':
            raise AgentError('TEST_LIFECYCLE_MUST_BE_INJECTED')
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'agent-process.log').open('ab') as log:
            command = [sys.executable, '-B', str(self.project / 'market_data_agent.py'), '--data-root', str(self.root), '--source', 'USER', '--enable-market-network']
            if paused:
                command.append('--start-paused')
            self.process = subprocess.Popen(command, cwd=self.project, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
        for _ in range(100):
            try:
                return self.query()
            except AgentError as error:
                if error.code != 'AGENT_UNAVAILABLE':
                    raise
                time.sleep(.1)
        raise AgentError('AGENT_START_FAILED')

    def collect(self):
        self.client.request('/v1/collection/start', {'confirmation': 'START_APPROVED_SOURCE'})
        for _ in range(100):
            value = self.query()
            if value['agent_state'] == 'RUNNING':
                return value
            time.sleep(.1)
        raise AgentError('AGENT_NOT_RUNNING')

    def stop(self):
        status = self.status()
        if status['status'] == 'ERROR':
            raise AgentError(status['error'])
        if 'identity' in status:
            self.client.request('/v1/shutdown', {'confirm': 'STOP_DATA_SERVICE'})
        # OS lease is the stop proof; an unreachable endpoint alone is insufficient.
        from adapters.runtime_lease import runtime_lease
        for _ in range(200):
            try:
                with runtime_lease(self.root):
                    break
            except RuntimeError:
                time.sleep(.1)
        else:
            raise AgentError('AGENT_STOP_NOT_CONFIRMED')
        activation = self.root / 'activation.json'
        if activation.exists():
            value = json.loads(activation.read_text(encoding='utf-8'))
            self.write_record('activation.json', {**value, 'collection_enabled': False})
        return {'status': 'STOPPED', 'stop_evidence': 'OS_LEASE_RELEASED'}
