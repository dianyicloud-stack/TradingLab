"""TEST-only provider response; production uses the original frozen Provider unchanged."""
def fixture_coordinator(original):
    class FixtureProvider:
        def analyze_event(self, handoff, **kwargs):
            return {'analysis':{'market_state':'测试震荡','structure_state':'TEST fixture 结构', 'action':'WATCH',
                'key_levels':{'support':24.6,'reference':24.93,'resistance':25.2},'invalidation':'TEST 失效条件',
                'reason_summary':['TEST 固定证据，不是真实AI分析'],'confidence':0.78},
                'usage_records':[{'success':True,'latency_ms':1,'input_tokens':1,'output_tokens':1,'total_tokens':2,'structured_output':True}]}
    def factory(*args, **kwargs):
        return original(*args,**kwargs,provider_factory=lambda *a,**k:FixtureProvider())
    return factory
