const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..'),s=fs.readFileSync(path.join(root,'app/live/static/live.js'),'utf8');
const context=vm.createContext({});
vm.runInContext(s.slice(s.indexOf('  const labels='),s.indexOf('  const text='))+
  s.slice(s.indexOf('  function directionClass('),s.indexOf('  function prose('))+'\nthis.renderText=chinese;this.direction=directionClass;',context);
const check=(source,expected)=>assert.strictEqual(context.renderText(source),expected);
check('因此判定为STRENGTHENED而非CONFIRMED','因此判定为增强但未确认而非确认');
check('FAILED WINDOW / INPUT_BUDGET / INVALID / WAIT','失败分析窗口 / 输入预算不足 / 无效 / 等待');
check('alpha尚未转正，VWAP上方WAIT','alpha尚未转正，VWAP上方等待');
check('WAITING_FIRST_DATA','等待首条数据');
check('WAITING_CUSTOM_ID','WAITING_CUSTOM_ID'); // Never corrupt identifiers through substring replacement.
for(const [before,after,key,style] of [[1,2,'price','change-up'],[2,1,'price','change-down'],[2,2,'price','change-flat'],['LOW','HIGH','risk_level','change-down'],['HIGH','LOW','risk_level','change-up'],[.15,.25,'target_weight','change-up'],[80,60,'confidence','change-down'],['WATCH','HOLD','action','change-flat']])assert.strictEqual(context.direction(before,after,key),style);
const samplesPath=path.join(root,'artifacts/live_readability_20260921/private/display-strings.json');
let sampleCount=0;
if(fs.existsSync(samplesPath)){
  const samples=JSON.parse(fs.readFileSync(samplesPath,'utf8'));sampleCount=samples.length;
  for(const sample of samples)for(const text of sample.strings){
    const translated=context.renderText(text);
    assert(!/(?<![A-Za-z0-9_])(?:STRENGTHENED|CONFIRMED|WAIT|INVALID|FAILED|INPUT_BUDGET|BUYER|SELLER|WEAKENED|UNCHANGED|INVALIDATED)(?![A-Za-z0-9_])/.test(translated));
  }
}
const result={status:'PASS',fixed_assertions:13,real_saved_opinions_checked:sampleCount,mutation:'NONE'};
fs.writeFileSync(path.join(root,'artifacts/live_readability_20260921/locale-check.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
