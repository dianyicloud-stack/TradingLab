import {createInterface} from 'node:readline';
import {createRuntime} from './runtime.mjs';
let runtime=null;
for await (const line of createInterface({input:process.stdin,crlfDelay:Infinity})) {
  try {const input=JSON.parse(line);if(input.op==='initialize'){runtime=createRuntime(input.state,{network:input.network===true,now:input.now});process.stdout.write(JSON.stringify({ok:true,value:{version:'market-core-1.0',node:process.version}})+'\n');continue;}
    if(!runtime)throw new Error('AGENT_NOT_INITIALIZED');
    const value=await runtime.execute(input);process.stdout.write(JSON.stringify({ok:true,value})+'\n');
  }catch(error){process.stdout.write(JSON.stringify({ok:false,error:error.message,code:error.code||'AGENT_CORE_ERROR'})+'\n');}
}
