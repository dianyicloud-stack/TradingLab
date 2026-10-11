"""Read-only fixed-source page; historical switching URLs explicitly retired."""
from pathlib import Path
from contracts.live.market_agent import AgentError
PAGE='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>行情服务 · Trading Lab</title><link rel="stylesheet" href="/assets/shell.css"></head><body><main style="max-width:960px;margin:32px auto;padding:24px"><nav><a href="/system">System</a> · <a href="/live">Live</a> · <a href="/data-observation">数据观察</a></nav><h1>行情服务</h1><p>正式行情固定来自 Market Data Agent。</p><section class="panel"><h2 id="source-name">Market Data Agent</h2><p id="source-notice" role="status">正在核实连接…</p><div id="source-summary"></div></section><details><summary>服务诊断</summary><pre id="source-diagnostics" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre><p>启动与迁机步骤：项目 docs/MACHINE_MIGRATION.md。服务不可用时不会读取其他行情源。</p></details><script src="/assets/market-source.js" defer></script></main></body></html>'
class SourceRouter:
    def __init__(self,service):self.service=service
    def accepts_post(self,path):return path in ('/api/system/market-agent/start','/api/system/market-agent/stop')
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/system/market-source':return 200,PAGE.encode(),'text/html; charset=utf-8'
        if method=='GET' and path=='/assets/market-source.js':return 200,Path(__file__).with_name('static').joinpath('market-source.js').read_bytes(),'text/javascript; charset=utf-8'
        if not path.startswith('/api/system/market-'):return None
        try:
            if method=='GET' and path=='/api/system/market-source':return 200,self.service.status(),None
            if method=='GET' and path=='/api/system/market-agent/status':return 200,self.service.lifecycle.status(),None
            if method=='GET' and path=='/api/system/market-source/history':
                data=self.service.repo.read();return 200,{'operations':data['operations'],'migrations':data.get('migrations',[])},None
            if path.startswith('/api/system/market-source'):
                return 404,{'error':'NOT_FOUND'},None
            if method=='POST' and path in ('/api/system/market-agent/start','/api/system/market-agent/stop'):
                import os
                if os.environ.get('TRADING_LAB_MANAGED_SERVICE')=='web':
                    from app.system.runtime_control import control_request
                    return 202,control_request(Path(os.environ['TRADING_LAB_DATA_ROOT']),{'action':path.rsplit('/',1)[1],'target':'agent'}),None
                return 200,self.service.agent_control(path.rsplit('/',1)[1],payload or {}),None
            return 404,{'error':'SOURCE_ENDPOINT_NOT_FOUND'},None
        except (AgentError,OSError,ValueError) as e:return getattr(e,'status',409),{'error':getattr(e,'code','SOURCE_OPERATION_FAILED'),'message':str(e)},None
