"""History API inside the observation/Live domains; no fifth product module."""
from pathlib import Path
import json,re
from contracts.history.bars import HistoryError,request

class HistoryRouter:
    def __init__(self,bars,analysis,store):self.bars,self.analysis,self.store=bars,analysis,store
    def accepts_post(self,path):return path=='/api/history/analyses'
    def accepts_put(self,path):return path=='/api/history/preferences'
    def close(self):self.analysis.close()
    def start_maintenance(self):self.analysis.start_maintenance()
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/assets/reading-format.js':
            from contracts.live.presentation import TERMS
            code='window.TradingLabTerms='+json.dumps(TERMS,ensure_ascii=False)+';\n'
            code+=Path(__file__).with_name('static').joinpath('reading-format.js').read_text(encoding='utf-8')
            return 200,code.encode(),'text/javascript; charset=utf-8'
        assets={'/assets/history.js':('history.js','text/javascript'),'/assets/history.css':('history.css','text/css'),
            '/assets/lightweight-charts-5.0.8.js':('vendor/lightweight-charts-5.0.8.js','text/javascript'),
            '/assets/charts-notice':('vendor/NOTICE.lightweight-charts','text/plain'),'/assets/charts-license':('vendor/LICENSE.lightweight-charts','text/plain')}
        if method=='GET' and path in assets:
            name,mime=assets[path];return 200,Path(__file__).with_name('static').joinpath(name).read_bytes(),mime+'; charset=utf-8'
        if not path.startswith('/api/history/'):return None
        p=payload or {}
        try:
            if path=='/api/history/bars' and method=='GET':return 200,self.bars.read(p),None
            if path=='/api/history/analyses' and method=='POST':return 202,self.analysis.submit(p),None
            if path=='/api/history/analyses' and method=='GET':
                from engines.history.bars import TZ
                cursor=p.get('before')
                if cursor and len(cursor)>256:raise HistoryError('INVALID_CURSOR','历史列表分页位置无效。',400)
                return 200,self.store.today(self.bars.clock().astimezone(TZ).date().isoformat(),cursor),None
            if method=='GET' and re.fullmatch(r'/api/history/analyses/HIST-[a-f0-9]{32}',path):return 200,self.analysis.detail(path.rsplit('/',1)[1]),None
            if path=='/api/history/preferences':
                symbol=p.get('symbol','')
                if not re.fullmatch(r'(sh|sz|bj)\d{6}',symbol):raise HistoryError('INVALID_SYMBOL','股票代码无效。',400)
                if method=='PUT':
                    value=request({**p,'end_date':self.bars.clock().date().isoformat()})
                    value={k:value[k] for k in ('period','volume_period','samples','limit','adjustment')}
                    with self.store.db() as db:db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)',(symbol,json.dumps(value)))
                    return 200,value,None
                if method=='GET':
                    with self.store.db() as db:row=db.execute('SELECT body FROM preferences WHERE symbol=?',(symbol,)).fetchone()
                    return 200,json.loads(row[0]) if row else {},None
            return 404,{'error':'NOT_FOUND'},None
        except HistoryError as e:return e.http_status,{'error':e.code,'message':str(e)},None
