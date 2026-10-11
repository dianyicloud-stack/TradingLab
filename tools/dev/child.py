"""DEV process boundary. No business logic; fail closed for external network."""
import ctypes, ipaddress, os, runpy, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEV=ROOT/'.dev'
# A process-local Windows job ensures a crashed DEV parent cannot strand its
# own Node worker. Existing unrelated processes are never assigned to this job.
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateJobObjectW.restype=ctypes.c_void_p
kernel.SetInformationJobObject.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32]
kernel.AssignProcessToJobObject.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
kernel.GetCurrentProcess.restype=ctypes.c_void_p
job=kernel.CreateJobObjectW(None,None)
limits=ctypes.create_string_buffer(144) # JOBOBJECT_EXTENDED_LIMIT_INFORMATION, x64
ctypes.c_uint32.from_buffer(limits,16).value=0x2000 # KILL_ON_JOB_CLOSE
if not job or not kernel.SetInformationJobObject(job,9,limits,144) or not kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess()):
    raise SystemExit('DEV_PROCESS_JOB_FAILED')
def inside_dev(value):
    if isinstance(value,int):return True
    if os.fsdecode(value).lower()=='nul':return True
    return Path(os.fsdecode(value)).resolve().is_relative_to(DEV)
def audit(event,args):
    if event=='subprocess.Popen':
        executable,command,_,_=args
        # Only the existing non-network native Worker is needed by TEST Agent.
        expected=[str(DEV/'runtime/node/node.exe'),str(ROOT/'engines/live/market_agent/worker.mjs')]
        version=[expected[0],'--version']
        if command not in (expected,version,subprocess.list2cmdline(expected),subprocess.list2cmdline(version)) or (executable and Path(executable).resolve()!=DEV/'runtime/node/node.exe'):
            raise PermissionError('DEV_CHILD_PROCESS_DISABLED: real AI and uncontrolled service launch are disabled')
    if event=='open':
        path,mode,flags=args
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        if writing and not inside_dev(path):raise PermissionError('DEV_WRITE_OUTSIDE_SANDBOX')
    if event=='sqlite3.connect' and str(args[0])!=':memory:':
        value=str(args[0])
        if value.startswith('file:'):
            from urllib.parse import urlsplit,unquote
            parsed=urlsplit(value)
            if parsed.netloc:raise PermissionError('DEV_DATABASE_UNC_DENIED')
            value=unquote(parsed.path)
            if len(value)>2 and value[0]=='/' and value[2]==':':value=value[1:]
        if not inside_dev(value):raise PermissionError('DEV_DATABASE_OUTSIDE_SANDBOX: '+value)
    if event=='socket.getaddrinfo':
        host=args[0]
        if host not in ('localhost','127.0.0.1','::1',None):raise PermissionError('DEV_EXTERNAL_NETWORK_DISABLED')
    if event=='socket.connect':
        address=args[1]
        if isinstance(address,tuple) and not ipaddress.ip_address(address[0]).is_loopback:raise PermissionError('DEV_EXTERNAL_NETWORK_DISABLED')
sys.addaudithook(audit)
sys.path.insert(0,str(ROOT))
target=sys.argv.pop(1)
if target not in ('trading_lab.py','market_data_agent.py'):raise SystemExit('DEV_TARGET_DENIED')
runpy.run_path(str(ROOT/target),run_name='__main__')
