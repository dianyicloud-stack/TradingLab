const fs=require('fs');
const [base,out]=process.argv.slice(2);const results=[];
(async()=>{for(const close of [false,true]){const started=Date.now();let completed=0,failures=[];
 for(let wave=0;wave<100;wave++)await Promise.all(Array.from({length:8},async()=>{try{const r=await fetch(base+'/healthz',{headers:close?{'Connection':'close'}:{},signal:AbortSignal.timeout(10000)});await r.text();if(!r.ok)throw Error('HTTP '+r.status);completed++;}catch(e){failures.push({name:e.name,message:e.message,code:e.code,cause:e.cause&&{code:e.cause.code,message:e.cause.message,syscall:e.cause.syscall,socket:e.cause.socket}});}}));
 results.push({connection_close:close,completed,failures,elapsed_ms:Date.now()-started});fs.writeFileSync(out,JSON.stringify(results,null,2));}
 console.log(JSON.stringify(results.map(r=>({...r,failures:r.failures.slice(0,3),failure_count:r.failures.length}))));})();
