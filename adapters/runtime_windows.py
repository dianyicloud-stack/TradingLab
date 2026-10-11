"""Windows Task Scheduler adapter. No passwords or machine-wide policy changes."""
from pathlib import Path
import hashlib,json,os,subprocess
from app.system.runtime_state import RuntimeState

def startup(project,root,action,port):
    if os.name!='nt':raise ValueError('WINDOWS_STARTUP_ONLY_NOT_HOST_TESTED')
    project=Path(project).resolve();root=Path(root).resolve()
    name='TradingLab-Supervisor-'+hashlib.sha256(str(project).lower().encode()).hexdigest()[:10]
    def quote(value):return "'"+str(value).replace("'","''")+"'"
    prefix="$ErrorActionPreference='Stop'; $name="+quote(name)+"; "
    if action=='install-startup':
        python=project/'.venv/Scripts/python.exe'
        if not python.is_file():raise ValueError('LOCAL_VENV_REQUIRED')
        # Task remains attached to foreground supervisor; restart settings bounded.
        arguments=f'-B "{project / "tools/runtime_control.py"}" serve --port {int(port)}'
        script=prefix+"""$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;
if ($user -match 'sandbox|SYSTEM$') { throw 'INTERACTIVE_OWNER_IDENTITY_REQUIRED' }
$a=New-ScheduledTaskAction -Execute PYTHON -Argument ARGUMENTS -WorkingDirectory PROJECT;
$t=New-ScheduledTaskTrigger -AtLogOn -User $user;
$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable;
$p=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited;
Register-ScheduledTask -TaskName $name -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null;
$task=Get-ScheduledTask -TaskName $name; @{TaskName=$task.TaskName;State=[string]$task.State;User=$task.Principal.UserId;LogonType=[string]$task.Principal.LogonType;ExecutionTimeLimit=$task.Settings.ExecutionTimeLimit;MultipleInstances=[string]$task.Settings.MultipleInstances;RunOnlyIfIdle=$task.Settings.RunOnlyIfIdle;RestartCount=$task.Settings.RestartCount;RestartInterval=$task.Settings.RestartInterval;Executable=$task.Actions.Execute;Arguments=$task.Actions.Arguments;WorkingDirectory=$task.Actions.WorkingDirectory;Trigger=$task.Triggers.CimClass.CimClassName}|ConvertTo-Json -Depth 3
""".replace('PYTHON',quote(python)).replace('ARGUMENTS',quote(arguments)).replace('PROJECT',quote(project))
    elif action=='disable-startup':script=prefix+"Disable-ScheduledTask -TaskName $name | Select-Object TaskName,State | ConvertTo-Json"
    elif action=='uninstall-startup':script=prefix+"Unregister-ScheduledTask -TaskName $name -Confirm:$false; @{status='UNINSTALLED';task=$name}|ConvertTo-Json"
    else:script=prefix+"$task=Get-ScheduledTask -TaskName $name; @{TaskName=$task.TaskName;State=[string]$task.State;User=$task.Principal.UserId;LogonType=[string]$task.Principal.LogonType;ExecutionTimeLimit=$task.Settings.ExecutionTimeLimit;MultipleInstances=[string]$task.Settings.MultipleInstances;RunOnlyIfIdle=$task.Settings.RunOnlyIfIdle;RestartCount=$task.Settings.RestartCount;RestartInterval=$task.Settings.RestartInterval;Executable=$task.Actions.Execute;Arguments=$task.Actions.Arguments;WorkingDirectory=$task.Actions.WorkingDirectory;Trigger=$task.Triggers.CimClass.CimClassName}|ConvertTo-Json -Depth 3"
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,encoding='utf-8',errors='replace',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:raise ValueError('TASK_SCHEDULER_ACCESS_OR_CONFIGURATION_ERROR: '+r.stderr[-600:])
    result=json.loads(r.stdout)
    if action=='install-startup':RuntimeState(root).update({'startup':'LOGON'})
    if action in ('disable-startup','uninstall-startup'):RuntimeState(root).update({'startup':'MANUAL'})
    return result

def launch(project):
    project=Path(project).resolve()
    name='TradingLab-Supervisor-'+hashlib.sha256(str(project).lower().encode()).hexdigest()[:10]
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"$ErrorActionPreference='Stop'; Start-ScheduledTask -TaskName '"+name+"'"],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode:raise ValueError('TASK_START_FAILED_USE_LOCAL_TASK_SCHEDULER')
