"""Value-only retention contract; owners never expose a writable database handle."""
from dataclasses import dataclass

@dataclass(frozen=True)
class RetentionBoundary:
    keep_day:str
    protected_opinions:tuple=()
    protected_sessions:tuple=()
    run_id:str=''

POLICY={'version':'LATEST_READY_TRADING_DAY_V1','enabled':False,'daily_detail_days':1,
        'local_snapshots_enabled':True,
        'timezone':'Asia/Shanghai','batch_rows':100,'backup_max_count':2,'backup_days':14,
        'backup_owner_cap_bytes':536870912,'logs_max_bytes':10485760,'logs_keep_days':7,
        'test_artifacts_max_bytes':268435456,'test_artifacts_keep_days':7,
        'rollback_max_count':2,'rollback_keep_days':14}

SNAPSHOT_OPTIONS={'cap':POLICY['backup_owner_cap_bytes'],'max_count':POLICY['backup_max_count'],'valid_days':POLICY['backup_days']}
