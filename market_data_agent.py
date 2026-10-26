"""Standalone loopback Agent. Explicit start; never enables AI or account actions."""
import argparse,json,os,secrets,signal,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from adapters.runtime_lease import runtime_lease
from engines.live.market_agent.service import AgentService,node_path
from engines.account.rules import TradingCalendar
from contracts.live.market_agent import AgentError

def serve(service,root,port=0):
    token=secrets.token_hex(32)
    from adapters.runtime_platform import identity,build
    from app.system.runtime_state import atomic
    import uuid
    instance_id=uuid.uuid4().hex;project=Path(__file__).resolve().parent
    class Handler(BaseHTTPRequestHandler):
        def reply(self,value,status=200):
            body=json.dumps(value,ensure_ascii=False,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def authorized(self):
            return self.headers.get('Authorization')=='Bearer '+token and self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and self.headers.get('Origin') is None
        def do_GET(self):
            if not self.authorized():return self.reply({'error':'AGENT_ACCESS_DENIED'},403)
            if self.path=='/v1/health':return self.reply({'status':'UP','instance_id':instance_id,'progress':service.last_cycle,
                'collection':'RUNNING' if service.thread and service.thread.is_alive() else 'STOPPED',
                'error':getattr(service,'scheduler_error',None),'build':service.build_id})
            if self.path=='/v1/state':return self.reply({**service.query(), 'agent_identity': {'pid':os.getpid(),'root':str(Path(root).resolve()),'project':str(Path(__file__).resolve().parent),'build_version':'MarketAgent-1.1-cutover','db_schema':'1.0'}})
            return self.reply({'error':'NOT_FOUND'},404)
        def do_POST(self):
            if not self.authorized():return self.reply({'error':'AGENT_ACCESS_DENIED'},403)
            try:
                n=int(self.headers.get('Content-Length','0'))
                if n<1 or n>8192 or self.headers.get('Transfer-Encoding'):return self.reply({'error':'BODY_SIZE'},413)
                value=json.loads(self.rfile.read(n))
                if not isinstance(value,dict):return self.reply({'error':'INVALID_COMMAND'},400)
                if self.path=='/v1/commands':return self.reply(service.command(value))
                if self.path=='/v1/metadata':return self.reply(service.metadata(value))
                if self.path=='/v1/collection/start':
                    if value.get('confirmation')!='START_APPROVED_SOURCE' or service.source!='USER':raise AgentError('CONFIRMATION_REQUIRED')
                    service.start();return self.reply({'status':'STARTING'})
                if self.path=='/v1/shutdown':
                    if value.get('confirm')!='STOP_DATA_SERVICE':raise AgentError('CONFIRMATION_REQUIRED')
                    activation=Path(root)/'activation.json'
                    if activation.is_file() and value.get('preserve_activation') is not True:
                        settings=json.loads(activation.read_text(encoding='utf-8'));settings['collection_enabled']=False
                        pending=activation.with_suffix('.tmp');pending.write_text(json.dumps(settings),encoding='utf-8');pending.replace(activation)
                    self.reply({'status':'STOPPING'});threading.Thread(target=self.server.shutdown,daemon=True).start();return
                return self.reply({'error':'NOT_FOUND'},404)
            except AgentError as error:return self.reply({'error':error.code,'message':str(error)},error.status)
            except (ValueError,TypeError):return self.reply({'error':'INVALID_COMMAND'},400)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    descriptor=Path(root)/'connection.json';temp=descriptor.with_suffix('.tmp')
    atomic(descriptor,{'schema_version':'1.0',**identity(),'url':f'http://127.0.0.1:{server.server_port}','token':token,'source':service.source,
        'project':str(project),'data_root':str(Path(root).resolve()),'instance_id':instance_id,'build':build(project)})
    if os.name!='nt':descriptor.chmod(0o600)
    return server

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--data-root',type=Path,required=True);parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--source',choices=('USER','TEST'),default='TEST');parser.add_argument('--enable-market-network',action='store_true');parser.add_argument('--check',action='store_true');parser.add_argument('--start-paused',action='store_true')
    args=parser.parse_args(argv)
    from shared.logging import configure_logging
    configure_logging()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent/'.env',override=False)
    root=args.data_root.resolve()
    if args.check:print(json.dumps({'node':node_path(),'data_root':str(root),'source':args.source,'market_network':args.enable_market_network}));return 0
    if root==Path(__file__).resolve().parent or 'legacy' in [p.lower() for p in root.parts]:raise ValueError('AGENT_DATA_ROOT_REJECTED')
    # Production needs an explicit owner-approved activation record; CLI flags alone do not switch Live.
    if args.source=='USER':
        from adapters.market_agent_process import validate_activation
        if not validate_activation(Path(__file__).resolve().parent,root)['enabled']:raise ValueError('AGENT_ACTIVATION_REQUIRED')
    with runtime_lease(root):
        service=AgentService(root,source=args.source,network=args.enable_market_network,calendar=TradingCalendar().is_open)
        server=serve(service,root,args.port)
        try:
            if args.enable_market_network and not args.start_paused:service.start()
            print(f'Market Data Agent: {server.server_address[0]}:{server.server_port}',flush=True)
            server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close();service.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
