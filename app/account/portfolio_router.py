"""Explicit unified account API. No arbitrary data path or client quote input."""
import re
from pathlib import Path
from engines.account.rules import DEFAULT_POLICY
from contracts.account.portfolio import AccountError


class PortfolioRouter:
    def __init__(self,service):self.service=service

    def accepts_post(self,path):
        return path=='/api/accounts' or bool(re.fullmatch(r'/api/accounts/AC-[a-f0-9]{32}/(?:delete|manual/action|manual/preview|intents|reconcile|ownership|executions/EX-[a-f0-9]{32}/void|advisories/ADV-[a-f0-9]{32}/confirm)',path))

    def accepts_put(self,path):return path=='/api/accounts/execution-binding' or bool(re.fullmatch(r'/api/accounts/AC-[a-f0-9]{32}/settings',path))

    def route(self,method,path,payload=None):
        if method=='GET' and path in ('/assets/account.js','/assets/account-binding.js'):return 200,Path(__file__).with_name('static').joinpath(path.rsplit('/',1)[-1]).read_bytes(),'text/javascript; charset=utf-8'
        p=payload or {};service=self.service;engine=service.engine
        live=re.fullmatch(r'/api/live/([a-z]{2}\d{6})/portfolio-context',path)
        try:
            if path=='/api/accounts/execution-binding':
                if method=='GET':return 200,service.binding(),None
                if method=='PUT':return 200,service.bind(p),None
            if live and method=='GET':return 200,service.context(live[1],refresh=False),None
            if path=='/api/accounts':
                if method=='GET':return 200,{'accounts':service.catalog(),'default_policy':DEFAULT_POLICY},None
                if method=='POST':return 201,service.create(p),None
            if not path.startswith('/api/accounts/'):return None
            m=re.fullmatch(r'/api/accounts/(AC-[a-f0-9]{32})(?:/(.*))?',path)
            if not m:return 404,{'error':'NOT_FOUND'},None
            account,part=m.groups()
            if method=='POST' and part=='delete':return 200,service.delete(account,p),None
            service.require_account(account)
            if method=='GET':
                if part not in (None,'positions','executions','valuation'):return 404,{'error':'NOT_FOUND'},None
                else:
                    state=service.state(account)
                    value=state if not part or part in ('valuation','reconciliation') else state.get(part)
                    if value is None:return 404,{'error':'NOT_FOUND'},None
                return 200,value,None
            if service.require_account(account)['account_type']!='LIVE_SHADOW':raise AccountError('ACCOUNT_READ_ONLY')
            if method=='PUT' and part=='settings':return 200,service.settings(account,p),None
            if method=='POST':
                if part=='manual/preview':return 200,service.preview(account,p),None
                if part in ('manual/action','intents'):return 200,service.manual(account,p),None
                if part=='reconcile':
                    if p.get('mode')!='REBUILD_FROM_LEDGER':raise AccountError('ACCOUNT_CORRECTION_NOT_AVAILABLE')
                    return 200,engine.reconcile(account,p.get('mode'),p.get('reason'),'LOCAL_USER'),None
                if part=='ownership':return 200,engine.ownership(account,p.get('lot_id'),p.get('ownership'),p.get('reason'),'LOCAL_USER'),None
                if part and part.startswith('executions/') and part.endswith('/void'):return 200,engine.void(account,part.split('/')[1],p.get('reason'),'LOCAL_USER'),None
                if part and part.startswith('advisories/') and part.endswith('/confirm'):return 200,service.confirm_advisory(account,part.split('/')[1],p),None
            return 404,{'error':'NOT_FOUND'},None
        except AccountError as error:
            return error.http_status,{'error':error.code,'message':str(error)},None
