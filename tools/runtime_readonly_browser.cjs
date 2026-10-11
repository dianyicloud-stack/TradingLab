// Runtime UI verification only: no controls, AI, accounts or notifications submitted.
const path=require('node:path');
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
(async()=>{
 const base=process.argv[2];if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base))throw Error('LOOPBACK_ONLY');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage(),errors=[],consoleErrors=[],blocked=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text())});
 await page.route('**/*',r=>{const q=r.request();if(!q.url().startsWith(base))return r.fulfill({status:200,body:''});if(q.method()!=='GET'&&!/\/read$/.test(new URL(q.url()).pathname)){blocked.push(q.url());return r.abort()}return r.continue()});
 const before=await (await fetch(base+'/api/system/runtime')).json();
 let report;
 try{
  await page.goto(base+'/system');await page.waitForFunction(()=>document.querySelectorAll('#runtime-services tr').length===2);
  const system=await page.locator('#runtime-center').innerText();
  if(!system.includes('登录后启动')||!system.includes('运行中'))throw Error('RUNTIME_STATUS_NOT_RENDERED');
  await page.goto(base+'/live');await page.waitForFunction(()=>document.querySelector('#runtime-live-summary')?.textContent.includes('Telegram：'));
  report={system,live:await page.locator('#runtime-live-summary').innerText(),pageerror:errors,console_error:consoleErrors,blocked};
 }finally{await browser.close()}
 const after=await (await fetch(base+'/api/system/runtime')).json();
 report.browser_closed_services_alive=after.services.web.actual==='RUNNING'&&after.services.agent.actual==='RUNNING'&&before.instance_id===after.instance_id;
 console.log(JSON.stringify(report));if(errors.length||consoleErrors.length||blocked.length||!report.browser_closed_services_alive)process.exitCode=1;
})().catch(e=>{console.error(e.message);process.exitCode=1});
