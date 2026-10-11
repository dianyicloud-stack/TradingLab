"""Isolated read-load harness. TEST producer replays recorded facts; no real AI/Account commands.

Run with --seconds 3600 for the required sustained acceptance. The producer is
an HTTP Contract fixture, not the production Agent or a new market algorithm.
"""
from pathlib import Path
import argparse,copy,ctypes,json,os,subprocess,sys,tempfile,time,threading,urllib.request
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1]
class MemoryCounters(ctypes.Structure):
    _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]

def memory():
    from ctypes import wintypes
    c=MemoryCounters();c.cb=ctypes.sizeof(c)
    ctypes.windll.kernel32.GetCurrentProcess.restype=wintypes.HANDLE
    api=ctypes.windll.psapi.GetProcessMemoryInfo;api.argtypes=[wintypes.HANDLE,ctypes.POINTER(MemoryCounters),wintypes.DWORD]
    if not api(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(c),c.cb):raise ctypes.WinError()
    return {'pid':os.getpid(),'working_bytes':c.working,'private_bytes':c.private,'threads':threading.active_count()}

def producer(base,out):
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    value=json.loads((ROOT/'artifacts/m2_runtime_closure/before/owner-sample.json').read_text(encoding='utf-8'))
    day=value['trading_date'];sessions=[s for s in value['sessions'] if s['date']==day][:3];ids={s['tracking_session_id'] for s in sessions}
    value.update(source='TEST',sessions=sessions,analysis_state={},agent_identity={'root':str(base),'pid':os.getpid()},errors=[])
    value['facts']=[f for f in value['facts'] if f['kind'] in ('SNAPSHOT','OBSERVATION','EVENT') and f['payload'].get('tracking_session_id') in ids]
    for key in ('handoffs','receipts'):value.pop(key,None)
    lock=threading.Lock();control={'delay':0,'error':False,'paused':os.environ.get('TEST_PRODUCER_FROZEN')=='1','queries':0};stop=threading.Event();published=[b''];started=time.monotonic()
    def publish():published[0]=json.dumps(value,ensure_ascii=False).encode()
    publish()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/v1/state':
                control['queries']+=1
                time.sleep(min(8,float(control['delay'])))
                body=published[0] if not control['error'] else b'{"error":"TEST_OWNER_FAILURE"}'
                self.send_response(200 if not control['error'] else 503);self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except OSError:pass
            else:
                body=json.dumps({'memory':memory(),'facts':len(value['facts']),'fact_version':value['fact_version'],'control':control}).encode();self.send_response(200);self.end_headers();self.wfile.write(body)
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            for k in ('delay','error','paused'):
                if k in data:control[k]=data[k]
            self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    (base/'connection.json').write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}','token':'isolated-test'}))
    def grow():
        ticks=0
        while not stop.wait(5):
            if control['paused']:continue
            ticks+=1
            for sid in ids:
                row=next((f for f in reversed(value['facts']) if f['kind']=='SNAPSHOT' and f['payload']['tracking_session_id']==sid),None)
                if not row:continue
                new=copy.deepcopy(row);sample=new['payload']['sample'];stamp=datetime.fromisoformat(sample['timestamp'])+timedelta(seconds=5)
                point=stamp.isoformat();sample.update(timestamp=point,source_updated_at=point,trade_source_captured_at=point);new.update(identity='TEST-GROW-'+str(ticks)+'-'+sid,recorded_at=point,sha256=str(ticks).zfill(64));value['facts'].append(new)
                if ticks%60==0:
                    for kind in ('OBSERVATION','EVENT'):
                        old=next((f for f in reversed(value['facts']) if f['kind']==kind and f['payload']['tracking_session_id']==sid),None)
                        if not old:continue
                        item=copy.deepcopy(old);item.update(identity='TEST-'+kind+'-'+str(ticks)+'-'+sid,recorded_at=point,revision=1,sha256=str(ticks).zfill(64));p=item['payload']
                        if kind=='EVENT':p.update(event_seq=p['event_seq']+1,event_id=item['identity'],timestamp=point)
                        else:p['raw'].update(id=item['identity'],requestedTime=stamp.strftime('%H:%M'),stockDataTime=stamp.strftime('%H:%M'),capturedAt=stamp.strftime('%Y-%m-%d %H:%M:%S'))
                        value['facts'].append(item)
            value['fact_version']+=1;value['last_cycle_at']=point;publish()
    threading.Thread(target=grow,daemon=True).start()
    server.serve_forever()

def web(base,out,code):
    sys.path.insert(0,str(code))
    from app.shell.bootstrap import build_application
    from app.shell.server import make_server
    from shared.config import Settings
    from bridges.market_agent import AgentClient,AgentFactBridge
    from bridges.active_market_source import ActiveMarketSource
    from tests.support.provider import PlanProvider
    client=AgentClient(base/'agent','TEST');source=ActiveMarketSource(AgentFactBridge(client),{'active_market_source':'MARKET_AGENT','source_generation':'ISOLATED','market_agent_root':str(base/'agent')})
    provider=PlanProvider();app=build_application(Settings(ROOT,data_root=base/'data',source='TEST',test_run_id='runtime-closure'),live_bridge=source,advisory_provider=provider,agent_client=client)
    for router in app.routers:
        if type(router).__name__=='ObservationRouter':router.active_source=source
        if hasattr(router,'start_read_model'):router.start_read_model(base/'data/runtime/live/read_model/latest.json')
        if hasattr(router,'start_observation_model'):router.start_observation_model(base/'data/runtime/live/observation_read_model/latest.json')
    server=make_server(app,0);threading.Thread(target=server.serve_forever,daemon=True).start()
    (out/'web.json').write_text(json.dumps({'url':f'http://127.0.0.1:{server.server_port}','pid':os.getpid()}))
    while not (out/'stop').exists():
        rows={'at':time.time(),'memory':memory(),'timings':server.performance.snapshot() if hasattr(server,'performance') else {'status':'NOT_IN_OLD_CODE'}}
        tmp=out/'resources.tmp';tmp.write_text(json.dumps(rows));tmp.replace(out/'resources.json');time.sleep(5)
    server.shutdown();server.server_close()
    for router in app.routers:
        if hasattr(router,'close'):router.close()
    app.live_loop.stop();app.live_loop.advisory._auto_pool.shutdown(wait=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--role',choices=('run','web','producer'),default='run');parser.add_argument('--base',type=Path);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--code',type=Path,default=ROOT);parser.add_argument('--seconds',type=int,default=3600);parser.add_argument('--frozen',action='store_true');args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.role=='producer':producer(args.base/'agent',out);return
    if args.role=='web':web(args.base,out,args.code);return
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='runtime-closure-') as temp:
        base=Path(temp);(base/'agent').mkdir();processes=[];logs=[]
        try:
            for role in ('producer','web'):
                log=(out/(role+'.log')).open('w',encoding='utf-8');logs.append(log);env=dict(os.environ)
                if args.frozen:env['TEST_PRODUCER_FROZEN']='1'
                if args.code==ROOT:env['TRADING_LAB_READ_TIMINGS']=str(out/'request-timings.jsonl')
                p=subprocess.Popen([sys.executable,'-B',__file__,'--role',role,'--base',str(base),'--out',str(out),'--code',str(args.code)],stdout=log,stderr=log,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));processes.append(p)
                target=base/'agent/connection.json' if role=='producer' else out/'web.json'
                for _ in range(200):
                    if target.exists():break
                    if p.poll() is not None:raise RuntimeError(role+' exited; inspect log')
                    time.sleep(.1)
                if not target.exists():raise RuntimeError(role+' readiness timeout')
            url=json.loads((out/'web.json').read_text())['url'];owner=json.loads((base/'agent/connection.json').read_text())['url']
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            result=subprocess.run([str(node),str(ROOT/'tools/runtime_closure_browser.js'),url,owner,str(out),str(args.seconds)],timeout=args.seconds+600)
            raise SystemExit(result.returncode)
        finally:
            (out/'stop').write_text('stop test only')
            for p in reversed(processes):
                try:p.wait(timeout=15)
                except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10)
            for log in logs:log.close()
if __name__=='__main__':main()
