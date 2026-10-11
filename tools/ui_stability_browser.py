"""Isolated TEST web: native fixtures + recorded observations, never production commands."""
from pathlib import Path
from threading import Thread
from dataclasses import replace
import sys,json,tempfile,subprocess,os,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from app.shell.server import make_server

def main():
    phase=sys.argv[1];out=ROOT/'artifacts/ui_stability'/phase/'browser';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='ui-stability-') as tmp:
        f=NativeFixture(Path(tmp));f.add_symbol('sz300225','测试丙');f.publish();f.advisory.market_is_open=lambda _:True
        for symbol in f.members:f.append(symbol);f.advisory.analyze(symbol)
        sample=json.loads((ROOT/'artifacts/ui_stability/before/api-data-observation-state.json').read_text(encoding='utf-8'))
        sample['source']='TEST';sample['source_generation']='UI-ISOLATED';sample['facts']=[x for x in sample['facts'] if x['kind'] in ('OBSERVATION','EVENT')];sample['sessions']=sample['sessions'][:1]
        original=copy.deepcopy(sample);sample['sessions']=[];sample['facts']=[]
        for i,symbol in enumerate(f.members):
            sid=f.members[symbol]['tracking_session_id'];session=copy.deepcopy(original['sessions'][0]);session.update(symbol=symbol,tracking_session_id=sid,stockName=['测试甲','测试乙','测试丙'][i],selectedBoardCode=f'BKTEST{i}',selectedBoardName=f'测试板块{i}');sample['sessions'].append(session)
            for fact in original['facts']:
                row=copy.deepcopy(fact);row['identity']=sid+row['identity'];row['payload'].update(symbol=symbol,tracking_session_id=sid)
                if row['kind']=='OBSERVATION':row['payload']['raw'].update(boardCode=f'BKTEST{i}',boardName=f'测试板块{i}')
                sample['facts'].append(row)
        class Control:
            def accepts_post(self,path):return path.startswith('/test/')
            def route(self,method,path,payload=None):
                if path=='/api/data-observation/state':return 200,copy.deepcopy(sample),None
                if path=='/test/tick':
                    for symbol in f.members:f.append(symbol,price=10+(len(f.native_events)%9)/10)
                    return 200,{'status':'TEST_APPENDED'},None
                if path=='/test/opinion':f.advisory.analyze('bj920161');return 200,{'status':'TEST_ANALYZED'},None
                if path=='/test/board':
                    sample['sessions'][0].update(selectedBoardCode='CHANGED',selectedBoardName='新确认板块');sample['version']+=1
                    return 200,{'status':'TEST_BOARD_CHANGED'},None
                if path=='/test/observation':
                    row=copy.deepcopy(next(x for x in reversed(sample['facts']) if x['kind']=='OBSERVATION' and x['payload']['symbol']=='bj920161'));row['identity']+='-next';row['payload']['raw']['id']+='-next';row['payload']['raw']['requestedTime']='15:01';sample['facts'].append(row);sample['fact_version']+=1
                    return 200,{'status':'TEST_ROW_APPENDED'},None
                return None
        app=replace(f.app,routers=(Control(),*f.app.routers));server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            return subprocess.run([str(node),str(ROOT/'tools/ui_stability_e2e.js'),f'http://127.0.0.1:{server.server_port}',str(out),phase],timeout=1500).returncode
        finally:
            server.shutdown();server.server_close();thread.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
