"""Read-only health aggregation over injected callbacks, no access to other stores."""
from contracts.system import HealthCheck
from threading import Lock, Thread
from copy import deepcopy
from datetime import datetime, timezone
import json

FAILURE_STATUSES = frozenset({"ERROR", "MISSING", "WARNING", "DEGRADED"})


class SystemHealth:
    def __init__(self, probes, cache_path=None):
        self._probes = tuple(probes)
        self._lock = Lock()
        self._cached = None
        self._running = False
        self.cache_path=cache_path
        if cache_path:
            try:
                cached=json.loads(cache_path.read_text(encoding='utf-8'))
                if {x['id'] for x in cached['checks'] if x['id']!='trading_lab'}=={x[0] for x in self._probes}:self._cached=cached
            except (OSError,ValueError):pass
        self._initial=[]
        # Bounded startup checks only. Large stores, full Hash and live-loop diagnostics
        # stay in the explicit background job. Never rerun these probes on page GET.
        for name,probe in self._probes:
            if name in {'configuration','account_stores'}:
                try:row=probe()
                except Exception:row=HealthCheck(name,name,'ERROR','启动检查失败')
                self._initial.append({**row.to_dict(),'checked_at':datetime.now(timezone.utc).isoformat()})
            else:
                label={'market_agent_source':'Market Data Agent','fast_advisory':'AI分析','listener':'实时监听'}.get(name,name)
                self._initial.append({**HealthCheck(name,label,'UNKNOWN','尚未运行深度诊断').to_dict(),'checked_at':None})

    def snapshot(self):
        checks = [HealthCheck("trading_lab", "Trading Lab", "UP", "Foundation v0.1 · local modular monolith")]
        for name, probe in self._probes:
            try:
                checks.append(probe())
            except Exception:
                checks.append(HealthCheck(name, name, "ERROR", "Health probe failed; inspect local diagnostics"))
        # Planned Foundation states (EMPTY, NOT_CONNECTED, NOT_IMPLEMENTED,
        # RESERVED and UNKNOWN) describe scope; they are not failures.
        degraded = any(check.status in FAILURE_STATUSES for check in checks)
        checked_at = datetime.now(timezone.utc).isoformat()
        value = {"service": "Trading Lab", "version": "0.1.0", "status": "UP",
                "overall": "DEGRADED" if degraded else "READY", "checked_at": checked_at,
                "checks": [{**check.to_dict(), 'checked_at':checked_at} for check in checks]}
        with self._lock:self._cached=deepcopy(value)
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.cache_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temporary.replace(self.cache_path)
        return value

    def read(self):
        """Page GET never runs probes, external calls, or business writes."""
        with self._lock:
            value=deepcopy(self._cached) if self._cached else {'service':'Trading Lab','status':'UP','overall':'UNKNOWN','checks':deepcopy(self._initial), 'checked_at':None}
            value['diagnostic_state']='RUNNING' if self._running else 'COMPLETE' if self._cached else 'NOT_RUN'
        return value

    def diagnose(self):
        with self._lock:
            if self._running:return {'status':'RUNNING'}
            self._running=True
        def run():
            try:self.snapshot()
            finally:
                with self._lock:self._running=False
        Thread(target=run,daemon=True,name='system-diagnostics').start()
        return {'status':'RUNNING'}
