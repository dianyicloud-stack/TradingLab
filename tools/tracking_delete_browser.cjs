const fs=require('fs'),path=require('path');
const {chromium}=require(path.resolve(path.dirname(process.execPath),'../node_modules/playwright'));
(async()=>{const base=process.argv[2],out=path.resolve(__dirname,'../artifacts/ai400_repair');
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const page=await browser.newPage(),result={checks:[],pageerror:[],consoleError:[]};
 page.on('pageerror',e=>result.pageerror.push(e.message));page.on('console',e=>{if(e.type()==='error')result.consoleError.push(e.text())});
 page.on('dialog',d=>d.accept());
 const check=(v,label)=>{if(!v)throw Error(label);result.checks.push(label)};
 try{
  await page.goto(base+'/live');await page.waitForSelector('#stock-sz301111');check(await page.locator('.advisory-card').count()===4,'four independent Live stocks before deletion');
  await page.goto(base+'/data-observation');await page.waitForSelector('#data-symbol option',{state:'attached'});
  await page.getByText('跟踪设置',{exact:true}).click();
  for(const symbol of ['sz301111','sz300504']){
   const row=page.locator('#tracking-list > div').filter({hasText:symbol});await row.getByRole('button',{name:'删除',exact:true}).click();
   await page.waitForFunction(s=>![...document.querySelectorAll('#data-symbol option')].some(o=>o.value===s),symbol);
   check(await page.locator('#tracking-list > div').filter({hasText:symbol}).count()===0,'owner deletion removes observation row '+symbol);
  }
  await page.reload();await page.waitForSelector('#data-symbol option',{state:'attached'});
  check(await page.locator('#data-symbol option').count()===2,'refresh does not restore deleted selectors');
  await page.goto(base+'/live');await page.waitForSelector('#stock-bj920161');
  check(await page.locator('.advisory-card').count()===2,'Live removes deleted stocks and retains two others');
  check(await page.locator('#stock-sz301111,#stock-sz300504').count()===0,'deleted Live cards absent');
  check(result.pageerror.length===0&&result.consoleError.length===0,'no browser runtime errors');result.status='PASS';
 }catch(e){result.status='FAIL';result.error=e.message;await page.screenshot({path:out+'/delete-browser-failure.png',fullPage:true});}
 finally{fs.writeFileSync(out+'/delete-browser.json',JSON.stringify(result,null,2));await browser.close();console.log(JSON.stringify(result));if(result.status!=='PASS')process.exitCode=1;}
})();
