const {createRequire}=require('node:module'),path=require('node:path');
const {chromium}=createRequire(__filename)(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
(async()=>{
const base=process.argv[2],send=process.argv.includes('--analyze');if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base))throw Error('LOOPBACK_REQUIRED');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}),page=await browser.newPage({viewport:{width:1365,height:900}}),errors=[],consoleErrors=[],requests=[];let analyses=0;
page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});page.on('request',r=>requests.push({method:r.method(),path:new URL(r.url()).pathname}));
await page.route('**/*',route=>{const r=route.request(),u=new URL(r.url());if(u.pathname==='/FD126C42-EBFA-4E12-B309-BB3FDD723AC1/main.js')return route.fulfill({status:200,contentType:'application/javascript',body:''});
 if(u.origin!==base)return route.abort();
 if(r.method()==='POST'&&u.pathname==='/api/history/analyses'){if(!send||++analyses>1)return route.abort();}
 else if(!['GET','HEAD'].includes(r.method())&&!(r.method()==='PUT'&&u.pathname==='/api/history/preferences'))return route.abort();
 return route.continue();});
try{
await page.goto(base+'/data-observation');await page.waitForTimeout(600);if(requests.some(r=>r.path==='/api/history/bars'))throw Error('EAGER_BARS_LOAD');
await page.locator('#history-panel>summary').click();await page.locator('#history-symbol').fill('bj920161');await page.locator('#history-symbol').dispatchEvent('change');await page.waitForTimeout(300);
await page.locator('#history-mode').selectOption('HISTORY_EOD');await page.locator('#history-date').fill('2026-09-24');await page.locator('#history-period').selectOption('DAY');await page.locator('#history-volume').selectOption('WEEK');await page.locator('#history-samples').selectOption('20');await page.locator('#history-load').click();
await page.waitForFunction(()=>document.querySelector('#history-status').textContent.includes('数据截至 2026-09-24'),null,{timeout:30000});
if(await page.locator('#history-chart canvas').count()===0)throw Error('NO_CANDLES');const chartStatus=await page.locator('#history-status').innerText();const volume=await page.locator('#history-volume-summary').innerText();
await page.locator('#history-chart').hover();await page.mouse.wheel(0,-150);await page.locator('#history-bar-inspect>summary').click();
if(!(await page.locator('#history-bar-data').innerText()).includes('data_version'))throw Error('NO_SOURCE_INSPECT');
// Delayed obsolete response may finish after the user changes period: it must not render.
await page.locator('#history-period').selectOption('MONTH');await page.locator('#history-load').click();await page.locator('#history-period').selectOption('DAY');await page.locator('#history-load').click();
await page.waitForFunction(()=>document.querySelector('#history-status').textContent.includes('· 日线 ·'),null,{timeout:30000});
let history=null;
const existing=process.argv.find(x=>x.startsWith('--existing='))?.slice(11);
if(existing&&!/^HIST-[a-f0-9]{32}$/.test(existing))throw Error('INVALID_EXISTING_ID');
if(send||existing){if(send){await page.locator('#history-analyze').click();await page.waitForURL(/\/live\?history=HIST-/, {timeout:15000});}else await page.goto(base+'/live?history='+existing);
 await page.waitForFunction(()=>/已完成|失败|已中断/.test(document.querySelector('#history-opinion-status').textContent),null,{timeout:270000});
 history={url:page.url(),status:await page.locator('#history-opinion-status').innerText(),evidence:await page.locator('#history-opinion-evidence').innerText(),result:await page.locator('#history-opinion-body').innerText()};
 if(!history.evidence.includes('有效样本'))throw Error('MISSING_FACTUAL_VOLUME_BASIS');
 if(!(await page.locator('#live-center').isHidden()))throw Error('LIVE_CONTEXT_VISIBLE');
 if(requests.some(r=>r.method==='POST'&&r.path!=='/api/history/analyses'))throw Error('HISTORICAL_SIDE_EFFECT_REQUEST');
}
console.log(JSON.stringify({chartStatus,volume,analyses,history,pageerror:errors,console_error:consoleErrors}));if(errors.length||consoleErrors.length)process.exitCode=1;
}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
