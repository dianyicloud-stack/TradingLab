"""Local process identity / bounded output; Windows-specific operations stay here."""
from pathlib import Path
import ctypes, hashlib, json, logging, logging.handlers, os, subprocess, sys, threading

def identity():
    executable=str(Path(sys.executable).resolve())
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype=wintypes.HANDLE
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),*[ctypes.byref(t) for t in times]):raise OSError('PROCESS_IDENTITY_FAILED')
        created=(times[0].dwHighDateTime<<32)+times[0].dwLowDateTime
        kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(kernel.GetCurrentProcess(),0,buffer,ctypes.byref(size)):raise OSError('PROCESS_EXECUTABLE_FAILED')
        executable=str(Path(buffer.value).resolve())
    else:
        created=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19] if sys.platform.startswith('linux') else None
    return {'pid':os.getpid(),'parent_pid':os.getppid(),'created':str(created),'executable':executable}

def alive(record):
    if not record:return False
    pid=record.get('pid')
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        from ctypes import wintypes
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.restype=wintypes.HANDLE;k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        k.CloseHandle.argtypes=[wintypes.HANDLE]
        k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        h=k.OpenProcess(0x1000,False,pid)
        if not h:return False
        try:
            times=[wintypes.FILETIME() for _ in range(4)];code=wintypes.DWORD()
            if not k.GetProcessTimes(h,*[ctypes.byref(t) for t in times]) or not k.GetExitCodeProcess(h,ctypes.byref(code)):return False
            return code.value==259 and str((times[0].dwHighDateTime<<32)+times[0].dwLowDateTime)==record.get('created')
        finally:k.CloseHandle(h)
    try:
        os.kill(pid,0)
        return str(Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19])==record['created']
    except (OSError,KeyError):return False

def process_table():
    if os.name!='nt':raise RuntimeError('PLATFORM_FORCE_CONTROL_NOT_VALIDATED')
    script="[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,@{Name='Created';Expression={$_.CreationDate.ToFileTimeUtc().ToString()}} | ConvertTo-Json -Compress"
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:raise RuntimeError('PROCESS_INSPECTION_DENIED')
    return json.loads(p.stdout)

def force_owned(record,project,data_root,service):
    """Explicit force only: verified process handle prevents PID reuse between check/kill."""
    project=Path(project).resolve();data_root=Path(data_root).resolve()
    if record.get('project')!=str(project) or record.get('data_root')!=str(data_root) or not record.get('instance_id'):raise RuntimeError('PROCESS_SCOPE_MISMATCH')
    table={p['ProcessId']:p for p in process_table()};p=table.get(record['pid'])
    entry=project/('trading_lab.py' if service=='web' else 'market_data_agent.py')
    if not p or Path(p.get('ExecutablePath') or '').resolve()!=Path(record['executable']) or str(entry).lower() not in (p.get('CommandLine') or '').lower() or not alive(record):raise RuntimeError('PROCESS_IDENTITY_CHANGED')
    # Children must have BOTH a verified parent chain and an allowlisted project worker.
    owned=[record['pid']];children=[]
    for _ in range(4):
        for item in table.values():
            pid=item['ProcessId'];cmd=(item.get('CommandLine') or '').lower()
            if pid in owned or item['ParentProcessId'] not in owned:continue
            if not any(str(project/x).lower() in cmd for x in ('adapters/ai/worker.py','engines/live/market_agent/worker.mjs')):
                raise RuntimeError('UNVERIFIED_CHILD_PROCESS')
            owned.append(pid);children.append(item)
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.restype=wintypes.HANDLE
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.CloseHandle.argtypes=[wintypes.HANDLE]
    k.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    k.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    # Hold exact process handles, then recheck parent identity before any termination.
    handles=[]
    try:
        for pid in [*reversed(owned[1:]),record['pid']]:
            handle=k.OpenProcess(0x1001,False,pid)
            if not handle:raise RuntimeError('PROCESS_ACCESS_DENIED')
            handles.append(handle)
            times=[wintypes.FILETIME() for _ in range(4)];buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
            if not k.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]) or not k.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):raise RuntimeError('PROCESS_IDENTITY_UNREADABLE')
            created=(times[0].dwHighDateTime<<32)+times[0].dwLowDateTime
            expected=record['created'] if pid==record['pid'] else table[pid]['Created']
            if abs(created-int(expected))>9 or Path(buffer.value).resolve()!=Path(table[pid]['ExecutablePath']).resolve():raise RuntimeError('PROCESS_IDENTITY_CHANGED')
        if not alive(record):raise RuntimeError('PROCESS_IDENTITY_CHANGED')
        for handle in handles:
            if not k.TerminateProcess(handle,1):raise RuntimeError('PROCESS_FORCE_FAILED')
    finally:
        for handle in handles:k.CloseHandle(handle)

def build(project):
    names=('trading_lab.py','market_data_agent.py','app/system/runtime_control.py','app/system/runtime_state.py',
        'app/system/runtime_web.py','adapters/runtime_platform.py','engines/live/loop.py')
    return hashlib.sha256(b''.join((Path(project)/n).read_bytes() for n in names)).hexdigest()[:16]

def spawn(command,project,log_path,env=None):
    """Services own bounded logs; adoption never leaves a broken parent pipe."""
    return subprocess.Popen(command,cwd=project,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
