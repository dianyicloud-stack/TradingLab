"""Local runtime control. All service targets and operations are allowlisted."""
from pathlib import Path
import argparse,json,os,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='Trading Lab 正式后台状态与控制',epilog='日常使用桌面 TradingLab 启动 / 停止 / 状态。trading_lab.py 保留为内部兼容、开发与验证入口。')
    p.add_argument('action',choices=('status','start','stop','restart','force-stop','force-restart','serve','install-startup','startup-status','disable-startup','uninstall-startup'))
    p.add_argument('target',nargs='?',choices=('background','web','agent'),default='background')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--desktop',action='store_true',help='中文日常入口；等待启停结果，启动成功后打开一次网页')
    args=p.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    root=Path(os.environ.get('TRADING_LAB_DATA_ROOT',ROOT/'data'))
    if not root.is_absolute():root=ROOT/root
    root=root.resolve()
    from app.system.runtime_control import ensure_supervisor,control_request,serve
    try:
        if args.desktop:
            from app.system.runtime_desktop import run
            return run(ROOT,root,args.action,args.port)
        if args.action=='serve':serve(ROOT,root,args.port);return 0
        if args.action.endswith('startup') or args.action=='startup-status':
            from adapters.runtime_windows import startup
            result=startup(ROOT,root,args.action,args.port)
        else:
            if args.action=='start':ensure_supervisor(ROOT,root,args.port)
            try:result=control_request(root,{'action':args.action,'target':args.target})
            except (OSError,ValueError):
                if args.action!='status':raise
                from app.system.runtime_state import RuntimeState
                result={'status':'SUPERVISOR_OFFLINE','desired':RuntimeState(root).read()}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,RuntimeError) as error:
        if args.desktop:
            from app.system.runtime_desktop import label
            print('操作未完成：'+label(str(error)))
        else:print(json.dumps({'status':'BLOCKED','reason':str(error)},ensure_ascii=False))
        return 1

if __name__=='__main__':raise SystemExit(main())
