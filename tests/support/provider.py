from copy import deepcopy

def analysis():
    return {'action':'WATCH','confidence':72,'current_state':'价格位于区间中部，量价尚未完成方向确认。',
      'game_state':'卖方尝试压价，但负向价格效率下降；买方以被动承接为主，尚未转为主动抬价。',
      'dominant_side':'SELLER','dominance_score':6,'dominance_trend':'WEAKENING',
      'core_conflict':'10.10附近承接能否转化为10.30以上主动抬价',
      'evidence':['成交增加但价格推动效率下降','价格仍在VWAP附近接受'],
      'invalidation':['10.10放量失守且Alpha继续恶化'],
      'key_levels':[{'label':'承接观察','price':10.1,'meaning':'观察被动承接能否维持'}],
      'scenario_tree':[{'scenario_id':'STRENGTHEN','label':'转强','conditions':['站上10.30','Alpha改善'],
        'interpretation':'买方从承接转为抬价','recommended_action':'等待确认后提高关注','confirmation':['上攻成交恢复'],'invalidation':['跌回10.10']}],
      'next_observation_focus':['10.30上方价格效率','Alpha是否修复'],
      'previous_hypothesis_review':{'status':'INSUFFICIENT_EVIDENCE','reason':'首次意见没有上一轮假设。'}}

class MockAdvisoryProvider:
    def __init__(self,callback=None):self.calls=[];self.callback=callback
    def catalog(self):return {'providers':[{'provider':'deepseek','models':['deepseek-v4-pro']},{'provider':'mock','models':['model-a']}],
                              'default_provider':'deepseek','default_model':'deepseek-v4-pro'}
    def analyze(self,frozen,provider,model,reasoning,prompt,schema):
        self.calls.append(deepcopy({'frozen':frozen,'provider':provider,'model':model,'reasoning':reasoning,'prompt':prompt}))
        if self.callback:self.callback()
        value=analysis()
        if frozen.get('previous_advisory'):value['previous_hypothesis_review']={'status':'WEAKENED','reason':'新证据显示原优势衰减。'}
        return {'analysis':value,'latency_ms':7,'provider':provider,'model':model}

class PlanProvider(MockAdvisoryProvider):
    def analyze(self,*args):
        result=super().analyze(*args)
        result["analysis"]["portfolio_plan"]={"portfolio_action":getattr(self,"action","OPEN"),"target_weight":getattr(self,"target",.25),"reason":"TEST fixture"}
        return result
