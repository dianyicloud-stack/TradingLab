(()=>{'use strict';const $=id=>document.getElementById(id);if(!$('ai-model-form'))return;
let state,busy=false;const zh={none:'不额外推理',low:'低',medium:'中',high:'高',xhigh:'更高',max:'最高'};
const say=(id,value)=>{$(id).textContent=value;};
async function api(path,body,method='POST'){const r=await fetch(path,{method:body?method:'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const v=await r.json();if(!r.ok)throw Error(v.message||'配置操作失败');return v;}
function options(el,rows,selected){el.replaceChildren(...rows.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=zh[x]||x;return o;}));if(rows.includes(selected))el.value=selected;}
function provider(){return state.catalog.providers.find(x=>x.provider===$('ai-provider').value);}
function effort(){options($('ai-effort'),provider()?.model_capabilities[$('ai-model').value]?.reasoning_efforts||[],state.default.reasoning_effort);}
function models(){const cached=state.remote_models?.[$('ai-provider').value];say('ai-model-directory',cached?cached.models.map(x=>`${x.id}（${x.supported?'能力已审核':'能力未审核'}）`).join('、')+` · 测量 ${cached.measured_at}`:'尚未主动刷新远程目录');options($('ai-model'),provider()?.models||[],state.default.model);effort();say('ai-connection',provider()?.error?'未配置 API 密钥；保存配置仍可用。':'密钥已配置；是否能生成分析以验证结果为准。');}
function render(v){state=v;options($('ai-provider'),v.catalog.providers.map(p=>p.provider),v.default.provider);models();$('ai-output').value=v.default.max_output_tokens??'';
say('ai-current',`当前默认：${v.default.provider} / ${v.default.model} / ${zh[v.default.reasoning_effort]||v.default.reasoning_effort} · 配置版本 ${v.revision}`);
if(v.draft){$('ai-manual-model').value=v.draft.model;say('ai-model-directory',`草稿 ${v.draft.model} 尚未启用；能力待核实。`);}
say('ai-config-source',`${v.env_path}。${v.credential_priority}`);
if(v.error)say('ai-result',v.error);else if(v.verification)say('ai-result',`最近验证：${v.verification.model_config.model} · ${v.verification.status==='PASS'?'通过':'未通过'} · ${v.verification.checked_at}`);
}
function selection(){return{provider:$('ai-provider').value,model:$('ai-model').value,reasoning_effort:$('ai-effort').value,...($('ai-output').value?{max_output_tokens:Number($('ai-output').value)}:{})};}
async function action(fn){if(busy)return;busy=true;try{await fn();}catch(e){say('ai-result',e.message);}finally{busy=false;}}
$('ai-provider').onchange=()=>{models();$('ai-output').value='';};$('ai-model').onchange=effort;
$('ai-model-form').onsubmit=e=>{e.preventDefault();action(async()=>{render(await api('/api/system/ai',selection(),'PUT'));say('ai-result','默认配置已保存，新任务使用新设置；没有调用 AI。');});};
$('ai-verify').onclick=()=>action(async()=>{if(!confirm('验证会使用合成历史证据，最多一次生成请求，可能产生 API 费用。继续？'))return;say('ai-result','正在验证，请勿重复点击…');const r=await api('/api/system/ai/verify',{selection:selection(),confirm_cost:true});say('ai-result',`${r.status==='PASS'?'验证通过':'验证未通过'} · ${r.message} ${r.error||''} · 实际尝试 ${r.attempts??'未知'}`);});
$('ai-draft').onclick=()=>action(async()=>{await api('/api/system/ai',{provider:$('ai-provider').value,model:$('ai-manual-model').value,draft:true},'PUT');say('ai-result','草稿已保存，未启用，也未调用 AI。');});
$('ai-refresh-models').onclick=()=>action(async()=>{const r=await api('/api/system/ai/models/refresh',{provider:$('ai-provider').value});say('ai-model-directory',r.models.map(x=>`${x.id}（${x.supported?'能力已审核':'能力未审核'}）`).join('、')+` · 测量 ${r.measured_at}`);});
api('/api/system/ai').then(render).catch(e=>say('ai-result',e.message));
})();
