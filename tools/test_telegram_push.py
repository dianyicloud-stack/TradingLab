"""Explicit one-message test. No Opinion, Provider or account writes."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from adapters.telegram import load_config,TelegramSender
from contracts.live.notification import format_opinion
from app.system.notifications import LABELS

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--send',action='store_true');args=parser.parse_args()
    config=load_config(ROOT)
    print('配置文件：'+config.env_path)
    print('配置状态：'+LABELS.get(config.state,config.state))
    text=format_opinion({'symbol':'000000','name':'推送测试','action':'WATCH',
        'game_state':'推送测试，非交易建议。','core_conflict':'验证本机通知配置和中文显示，不使用真实账户数据。',
        'next_observation_focus':['收到本条测试通知即表示本次投递得到验证；本测试不调用AI或产生交易。']})
    if not args.send:print('未发送；只有显式 --send 才进行一次投递。');return 0
    result=TelegramSender(config).send(text)
    print(json.dumps({'status':LABELS.get(result['state'],result['state']),**result},ensure_ascii=False))
    return 0 if result['state']=='SENT' else 1
if __name__=='__main__':raise SystemExit(main())
