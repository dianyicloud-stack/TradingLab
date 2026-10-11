"""Three-section projection of saved Opinion; same fields/labels as Live reading."""
import re
ACTION={'NO_ACTION':'观察','WATCH':'观察','WAIT':'等待','HOLD':'维持','ADD':'增加','REDUCE':'降低','EXIT':'退出','OPEN':'建仓','NONE':'不行动'}
WORDS={**ACTION,'BUYER':'买方','SELLER':'卖方','BALANCED':'平衡','UNCLEAR':'不明确',
       'STRENGTHENING':'增强','WEAKENING':'减弱','STABLE':'稳定','REVERSING':'反转',
       'CONFIRMED':'确认','STRENGTHENED':'增强但未确认','WEAKENED':'减弱','INVALIDATED':'已失效',
       'UNCHANGED':'保持不变','INSUFFICIENT_EVIDENCE':'证据不足','NEW_HIGH':'新高','NEW_LOW':'新低',
       'VWAP_RECLAIM':'重回VWAP上方','VWAP_LOST':'跌破VWAP','SUPPORT_RETEST':'支撑二测',
       'LOW_VOLUME_PULLBACK':'缩量回踩','ALPHA_DETERIORATE':'Alpha恶化','VOLUME_BREAKDOWN':'放量跌破'}
PATTERN=re.compile(r'(?<![A-Za-z0-9_])('+'|'.join(sorted(WORDS,key=len,reverse=True))+r')(?![A-Za-z0-9_])')
def chinese(value):
    return PATTERN.sub(lambda m:WORDS[m[0]],str(value)) if value not in (None,'') else '本轮未提供'
def format_opinion(opinion):
    game=opinion.get('game_state')
    summary=game if isinstance(game,str) else (game or {}).get('summary')
    summary=summary or opinion.get('current_state')
    action=ACTION.get(opinion.get('action'),'本轮未提供')
    focus=[]
    for row in opinion.get('next_observation_focus') or []:
        focus.append(chinese(row) if isinstance(row,str) else '；'.join(chinese(row.get(k)) for k in ('target','watch_for','meaning')))
    symbol=re.sub(r'^(bj|sh|sz)','',opinion.get('symbol',''),flags=re.I)
    return '\n\n'.join((f"【本轮结论｜{opinion.get('name') or '名称未提供'} {symbol}】\n{action}。{chinese(summary)}",
        '【核心依据】\n'+chinese(opinion.get('core_conflict')),
        '【接下来观察】\n'+('\n'.join(focus) or '本轮未提供')))

def split_message(text,limit=4096):
    """Lossless paragraph-preferred split, conservatively counted in UTF-16 units."""
    chunks=[]
    while text:
        units=0;end=0
        for c in text:
            n=2 if ord(c)>0xffff else 1
            if units+n>limit:break
            units+=n;end+=1
        if end<len(text):
            boundary=text.rfind('\n',0,end)
            if boundary>0:end=boundary+1
        chunks.append(text[:end]);text=text[end:]
    return chunks
