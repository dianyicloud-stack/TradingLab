const path=require('node:path'),{createRequire}=require('node:module'),assert=require('node:assert/strict');
const {chromium}=createRequire(__filename)(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
(async()=>{const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)||base.endsWith(':8765'))throw Error('ISOLATED_ONLY');
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}),context=await browser.newContext();const page=await context.newPage(),errors=[],consoleErrors=[];
page.on('pageerror',e=>errors.push(e.message));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text());});page.on('dialog',d=>d.accept());
try{
await page.goto(base+'/account');await page.waitForResponse(r=>r.url()===base+'/api/accounts');
async function create(name){await page.locator('#account-new').click();await page.locator('#account-name').fill(name);await page.locator('#initial-capital').fill('100000');await page.locator('#account-save').click();await page.waitForFunction(n=>document.querySelector('#account-summary').textContent.includes(n),name);return page.locator('#account-select').inputValue();}
const a=await create('浏览器组合A'),b=await create('浏览器组合B');
assert.notEqual(a,b);let binding=await (await context.request.get(base+'/api/accounts/execution-binding')).json();assert.equal(binding.account_id,null);
await page.goto(base+'/live');await page.waitForFunction(()=>document.querySelector('#execution-account').options.length===3);await page.locator('#execution-account').selectOption(a);await page.waitForFunction(()=>document.querySelector('#execution-account-state').textContent.includes('只给建议'));
await page.goto(base+'/account?account_id='+b);await page.waitForFunction(()=>document.querySelector('#account-summary').textContent.includes('浏览器组合B'));binding=await(await context.request.get(base+'/api/accounts/execution-binding')).json();assert.equal(binding.account_id,a);
await page.locator('#account-select').selectOption(a);await page.waitForFunction(()=>document.querySelector('#account-summary').textContent.includes('浏览器组合A'));await page.locator('#account-settings').click();await page.locator('#ai-execution').selectOption('AUTO_SHADOW_EXECUTION');await page.locator('#account-save').click();await page.waitForFunction(()=>document.querySelector('#account-mode').textContent.includes('自动影子执行'));
await page.locator('#account-pause').click();await page.waitForFunction(()=>document.querySelector('#account-mode').textContent.includes('已暂停'));await page.reload();await page.waitForFunction(()=>document.querySelector('#account-mode').textContent.includes('已暂停'));
await page.goto(base+'/live');await page.waitForFunction(()=>document.querySelector('#execution-account-state').textContent.includes('已暂停'));
await page.goto(base+'/account?account_id='+a);await page.waitForFunction(()=>document.querySelector('#account-summary').textContent.includes('浏览器组合A'));await page.locator('#account-delete').click();await page.waitForFunction(()=>document.querySelector('#account-message').textContent.includes('永久删除'));binding=await(await context.request.get(base+'/api/accounts/execution-binding')).json();assert.equal(binding.account_id,null);
await page.goto(base+'/live');await page.waitForFunction(()=>document.querySelector('#execution-account').options.length===2);assert.equal(await page.locator('#execution-account').inputValue(),'');
for(const p of ['/account','/data-observation','/system']){const r=await page.goto(base+p);assert.equal(r.status(),200);await page.waitForTimeout(300);}
assert.equal(await page.locator('#account-advanced,#account-show-all,#account-switch-history').count(),0);
console.log(JSON.stringify({status:'PASS',created:2,deleted:1,view_did_not_bind:true,mode_saved:true,pause_reload:true,delete_unbound:true,pageerror:errors,console_error:consoleErrors}));assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
