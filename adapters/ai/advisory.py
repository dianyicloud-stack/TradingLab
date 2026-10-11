"""Configuration-driven advisory transport reusing the existing isolated provider worker."""
from pathlib import Path
import os
import yaml
from dotenv import dotenv_values
from adapters.ai.transport import ProviderTransport


class AdvisoryProvider:
    def __init__(self, root):
        self.root=Path(root)
        self.transport=ProviderTransport(root)

    def catalog(self):
        config=yaml.safe_load((self.root/'config/ai.yaml').read_text(encoding='utf-8')) or {}
        providers=[]
        credentials={**dotenv_values(self.root/'.env'),**os.environ}
        # Read the existing transport's capability declaration without importing
        # or executing frozen code. Unknown providers do not inherit DeepSeek's options.
        from adapters.ai.config import DEEPSEEK_REASONING_EFFORTS
        from adapters.ai.capabilities import MODELS
        efforts=DEEPSEEK_REASONING_EFFORTS
        for identity,value in (config.get('ai',{}).get('providers',{}) or {}).items():
            if value.get('enabled') and value.get('model'):
                providers.append({'provider':identity,'models':list(MODELS.get(identity,{})),
                    'model_capabilities':MODELS.get(identity,{}),
                    'credential_source':'PROCESS_ENVIRONMENT' if value.get('api_key_env','') in os.environ else 'PROJECT_DOTENV',
                    'error':None if credentials.get(value.get('api_key_env',''),'') else 'API_KEY_MISSING'})
        default=config.get('ai',{}).get('default_provider','deepseek')
        selected=next((row for row in providers if row['provider']==default),providers[0] if providers else None)
        return {'providers':providers,'default_provider':selected['provider'] if selected else None,
                'default_model':config['ai']['providers'][selected['provider']]['model'] if selected else None}

    def connections(self):
        return (yaml.safe_load((self.root/'config/ai.yaml').read_text(encoding='utf-8')) or {}).get('ai',{}).get('providers',{})

    def list_models(self,provider):
        from adapters.ai.capabilities import ENDPOINTS,KEYS,MODELS
        from contracts.live.bridge import BridgeError
        from datetime import datetime,timezone
        import httpx
        if provider not in ENDPOINTS:raise BridgeError('INVALID_PROVIDER','不支持该服务商。',400)
        key={**dotenv_values(self.root/'.env'),**os.environ}.get(KEYS[provider])
        if not key:raise BridgeError('API_KEY_MISSING','尚未配置 API 密钥。',400)
        try:
            with httpx.Client(timeout=15,follow_redirects=False) as client:
                response=client.get(ENDPOINTS[provider]+'/models',headers={'Authorization':'Bearer '+key})
                response.raise_for_status();rows=response.json()['data']
            return {'measured_at':datetime.now(timezone.utc).isoformat(),'models':[{'id':r['id'],'supported':r['id'] in MODELS[provider]} for r in rows[:200] if isinstance(r.get('id'),str) and len(r['id'])<=100]}
        except Exception:raise BridgeError('MODEL_LIST_UNAVAILABLE','远程模型列表读取失败；已保存设置不变。',502) from None

    def analyze(self, frozen_input, provider, model, reasoning, prompt, schema):
        return self.transport.analyze(frozen_input,reasoning,'structure_first',prompt,schema,provider=provider,model=model,advisory_diagnostics=True)

    def analyze_recorded(self, frozen_input, provider, model, reasoning, prompt, schema, request_store):
        return self.transport.analyze(frozen_input,reasoning,'structure_first',prompt,schema,provider=provider,model=model,
            advisory_diagnostics=True,request_store=request_store)

    def analyze_history(self,frozen_input,provider,model,reasoning,prompt,schema,request_store,http_budget):
        http_budget.parent.mkdir(parents=True,exist_ok=True)
        return self.transport.analyze(frozen_input,reasoning,'structure_first',prompt,schema,provider=provider,model=model,
            advisory_diagnostics=True,request_store=request_store,http_budget_path=http_budget)
