(async()=>{
 const notice=document.querySelector('#source-notice');
 try {const response=await fetch('/api/system/market-source');if(!response.ok)throw Error('服务状态读取失败');const v=await response.json();notice.textContent=v.message;
 const summary=document.querySelector('#source-summary');
 for(const [label,value] of [['服务状态',v.agent.status],['行情目录',v.configuration.market_agent_root],['进程',v.agent.identity?.pid??'未连接'],['自启动',v.configuration.agent_auto_start?'已启用':'未启用']]){const p=document.createElement('p');p.textContent=label+'：'+value;summary.append(p);}
 document.querySelector('#source-diagnostics').textContent=JSON.stringify(v,null,2);
 }catch(e){notice.textContent='Market Data Agent 状态不可用：'+e.message;}
})();
