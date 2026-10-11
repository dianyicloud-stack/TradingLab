"""Trading Lab: Live, market observation, Account and System."""
import argparse
import json
import os
from pathlib import Path
import sys

from adapters.baselines import verify_baselines
from shared.config import Settings
from shared.logging import configure_logging
from adapters.runtime_lease import runtime_lease

PROJECT_ROOT = Path(__file__).resolve().parent


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Trading Lab (Live / 数据观察 / Account / System)")
    parser.add_argument("--port", type=int, default=8765, help="Loopback HTTP port; 0 selects an available port")
    parser.add_argument("--web-only",action="store_true",help="Load Web only; do not start or supervise the independent Agent")
    parser.add_argument('--managed',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument("--verify-baselines", action="store_true", help="Read-only frozen hash verification; 1 signals any mismatch")
    parser.add_argument("--init-only", action="store_true", help="Initialize Foundation stores and show health without starting HTTP")
    parser.add_argument('--check-agent',action='store_true',help='Read configured Agent dependencies and activation without starting collection')
    parser.add_argument('--stop-agent',action='store_true',help='Explicitly stop configured independent data service; preserve all facts')
    parser.add_argument('--market-source',help=argparse.SUPPRESS)
    parser.add_argument('--market-agent-root',type=Path,help='Explicit diagnostic/test override')
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT/'.env',override=False)
    configure_logging()
    try:
        configured_root = os.environ.get('TRADING_LAB_DATA_ROOT')
        data_root = Path(configured_root) if configured_root else PROJECT_ROOT/'data'
        if not data_root.is_absolute():data_root=PROJECT_ROOT/data_root
        source = os.environ.get('TRADING_LAB_SOURCE','USER')
        overrides={}
        if args.market_source:overrides['active_market_source']=args.market_source
        if args.market_agent_root:overrides['market_agent_root']=str(args.market_agent_root.resolve())
        if source=='USER' and not any((args.managed,args.web_only,args.init_only,args.verify_baselines,args.check_agent,args.stop_agent)):
            from app.system.runtime_control import ensure_supervisor,control_request
            ensure_supervisor(PROJECT_ROOT,data_root,args.port)
            print(json.dumps(control_request(data_root,{'action':'start','target':'background'}),ensure_ascii=False));return 0
        if args.check_agent or args.stop_agent:
            if args.stop_agent:
                from app.system.runtime_control import control_request
                print(json.dumps(control_request(data_root,{'action':'stop','target':'agent'})));return 0
            from adapters.market_agent_process import AgentSupervisor
            supervisor=AgentSupervisor(PROJECT_ROOT,data_root,source,overrides)
            if args.stop_agent:print(json.dumps(supervisor.client.request('/v1/shutdown',{'confirm':'STOP_DATA_SERVICE'})));return 0
            from engines.live.market_agent.service import node_path,NODE_VERSION
            print(json.dumps({**supervisor.configuration(),'node':node_path(),'node_version':NODE_VERSION}));return 0
        if args.verify_baselines:
            result = verify_baselines(PROJECT_ROOT)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["status"] == "READY" else 1
        from app.shell.bootstrap import build_application
        from app.shell.server import make_server
        configured_root = os.environ.get("TRADING_LAB_DATA_ROOT")
        data_root = Path(configured_root) if configured_root else None
        if data_root is not None and not data_root.is_absolute():
            data_root = PROJECT_ROOT / data_root
        source = os.environ.get("TRADING_LAB_SOURCE", "USER")
        test_run_id = os.environ.get("TRADING_LAB_TEST_RUN_ID")
        if not args.init_only:
            from adapters.web_instance import existing
            url=existing(data_root or PROJECT_ROOT/'data',source)
            if url:
                from adapters.source_configuration import source_configuration
                import urllib.request
                _,desired=source_configuration(PROJECT_ROOT,data_root or PROJECT_ROOT/'data',source,overrides)
                try:
                    with urllib.request.urlopen(url+'/api/system/market-source',timeout=3) as response:active=json.load(response)
                    if active['active_market_source']!=desired['active_market_source'] or active['configuration']['market_agent_root']!=desired['market_agent_root']:
                        raise ValueError('RUNNING_INSTANCE_SOURCE_DIFFERS: stop this instance before changing the configured Agent data root')
                except (OSError,KeyError):
                    if overrides.get('market_agent_root'):raise ValueError('RUNNING_INSTANCE_SOURCE_UNVERIFIED')
                print('Trading Lab 已运行：'+url+'（连接现有实例，未新建数据服务）',flush=True);return 0
        with runtime_lease(data_root or PROJECT_ROOT/'data'):
            from adapters.market_agent_process import AgentSupervisor
            supervisor=AgentSupervisor(PROJECT_ROOT,data_root,source,overrides)
            supervisor.repo.migrate()
            if supervisor.config.get('deprecated_ignored'):
                print('Deprecated source selectors ignored: '+', '.join(supervisor.config['deprecated_ignored']),flush=True)
            if source=='USER' and not args.init_only and not args.web_only and not args.managed:
                from contracts.live.market_agent import AgentError
                try:print('Market Data Agent: '+json.dumps(supervisor.ensure()),flush=True)
                except (AgentError,OSError,ValueError) as e:print('MARKET_AGENT unavailable: '+getattr(e,'code',type(e).__name__),flush=True)
                supervisor.watch()
            application = build_application(Settings(PROJECT_ROOT, args.port, data_root, source, test_run_id),market_source_overrides=overrides or None)
            if args.init_only:
                print(json.dumps(application.system_health.snapshot(), indent=2, ensure_ascii=False))
                return 0
            for router in application.routers:
                if hasattr(router,'start_maintenance'):router.start_maintenance()
                if hasattr(router,'start_read_model'):
                    router.start_read_model((data_root or PROJECT_ROOT/'data')/'runtime/live/read_model/latest.json')
                if hasattr(router,'start_observation_model'):
                    router.start_observation_model((data_root or PROJECT_ROOT/'data')/'runtime/live/observation_read_model/latest.json')
            with make_server(application, args.port) as server:
                from adapters.web_instance import publish
                import uuid
                import secrets
                server.control_token=secrets.token_hex(32)
                server.instance_id=uuid.uuid4().hex;publish(data_root or PROJECT_ROOT/'data',source,server,server.instance_id)
                application.runtime.server=server
                application.runtime.start()
                print(f"Trading Lab: http://127.0.0.1:{server.server_port}", flush=True)
                print("Local workspace. Press Ctrl+C to stop. See /live and /system.", flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    print("\nTrading Lab stopped.")
                finally:
                    supervisor.close()
                    application.runtime.close()
                    for router in application.routers:
                        if hasattr(router,'close'):router.close()
            return 0
    except ImportError:
        print("Install dependencies: .venv\\Scripts\\python.exe -m pip install -r requirements-lock.txt", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Trading Lab startup/check failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
