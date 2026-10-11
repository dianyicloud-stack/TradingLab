"""Offline copy only. Original data is retained; incomplete copies never start."""
from pathlib import Path
from contextlib import contextmanager,ExitStack,closing
import argparse,json,os,shutil,sqlite3,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from portable_control import ROOT,CORE,DATA,AGENT,configure,digest,load,Blocked

def tree(root):
    root=Path(root).absolute()
    if root.resolve()!=root:raise Blocked('来源或目标包含联接/符号链接；未复制。')
    result={}
    for directory,folders,files in os.walk(root,followlinks=False):
        for name in folders+files:
            p=Path(directory)/name
            if p.is_symlink() or p.is_junction():raise Blocked('不跟随联接/符号链接：'+str(p))
        for name in files:
            p=Path(directory)/name;result[p.relative_to(root).as_posix()]=digest(p)
    return result

@contextmanager
def stopped_lease(root):
    # Same service-owner lock, acquired without creating/changing the source file.
    import msvcrt
    path=root/'runtime/service.lock'
    if not path.is_file():raise Blocked('缺少可验证的原服务租约：'+str(path)+'；不推测来源已停止。')
    with path.open('r+b') as handle:
        handle.seek(1<<30)
        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise Blocked('来源服务仍在运行或无法取得其租约；没有停止或强杀来源服务。') from None
        try:yield
        finally:handle.seek(1<<30);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)

def migrate(source_core,source_agent,target,apply=False):
    from adapters.runtime_platform import alive
    from app.system.runtime_control import read
    source_core=Path(source_core).absolute();source_agent=Path(source_agent).absolute();target=Path(target).absolute()
    source_data=source_core/'data'
    for p in (source_core,source_agent,target):
        if p.resolve()!=p:raise Blocked('路径含联接或未规范化；未复制。')
    if target.exists():raise Blocked('目标必须是不存在的新目录；不覆盖现有数据。')
    roots=(source_core,source_agent,ROOT)
    if any(target.is_relative_to(p) or p.is_relative_to(target) for p in roots):raise Blocked('迁移目标与来源/发布包路径重叠。')
    if source_agent.is_relative_to(source_core) or source_core.is_relative_to(source_agent):raise Blocked('Agent 与程序目录必须分离。')
    if not source_data.is_dir() or not source_agent.is_dir() or not (source_core/'.env').is_file():raise Blocked('来源配置或数据目录不存在。')
    # Only migrate this exact code version; no implicit database schema migration.
    manifest=load(ROOT/'runtime/files.json')
    originals=load(ROOT/'runtime/source-original.json')
    for relative,expected in manifest.items():
        if relative.startswith('TradingLab/') and relative not in ('TradingLab/.env.example',):
            p=source_core/relative.removeprefix('TradingLab/')
            accepted={expected,originals.get(relative.removeprefix('TradingLab/'))}
            if not p.is_file() or digest(p) not in accepted:raise Blocked('来源代码不是此发布包版本；请单独核对升级兼容性：'+relative)
    for p in (source_data/'runtime/supervisor.json',source_data/'runtime/web-instance.json',source_agent/'connection.json'):
        if alive(read(p)):raise Blocked('来源仍有运行实例；先正常停止所有服务及管理者。')
    print('迁移为完整离线复制：保留来源，包含配置、全部 Core/Agent 数据、账户证据及游标；不迁移结构。')
    if not apply:
        print('仅检查参数；尚未取得租约/校验所有文件，未创建目标。使用 --apply 才复制。');return
    with ExitStack() as leases:
        for p in (source_data/'runtime/supervisor-lease',source_data,source_agent):leases.enter_context(stopped_lease(p))
        scopes={'TradingLab/data':source_data,'MarketDataAgent':source_agent,'TradingLab/config':source_core/'config'}
        before={name:tree(p) for name,p in scopes.items()};env_hash=digest(source_core/'.env')
        needed=sum((root/rel).stat().st_size for name,root in scopes.items() for rel in before[name])
        needed+=sum(p.stat().st_size for p in ROOT.rglob('*') if p.is_file())
        parent=target.parent
        while not parent.exists():parent=parent.parent
        if shutil.disk_usage(parent).free<needed*1.2+100*1024**2:raise Blocked('可用空间不足，未创建迁移副本。')
        target.mkdir(parents=True)
        (target/'MIGRATION_INCOMPLETE').write_text('Do not start. Original data remains intact.\n',encoding='utf-8')
        # Copy sealed runtime/application files only; never copy another release's runtime data.
        for rel,expected in manifest.items():
            if digest(ROOT/rel)!=expected:raise Blocked('发布包完整性校验失败：'+rel)
            dst=target/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,dst)
        shutil.copy2(ROOT/'runtime/files.json',target/'runtime/files.json')
        shutil.copy2(ROOT/'portable.json',target/'portable.json')
        for name,source in scopes.items():shutil.copytree(source,target/name,dirs_exist_ok=False)
        shutil.copy2(source_core/'.env',target/'TradingLab/.env')
        for name,source in scopes.items():
            if tree(source)!=before[name] or tree(target/name)!=before[name]:raise Blocked('复制期间来源变化或副本不完整；新目录保持禁止启动。')
        if digest(source_core/'.env')!=env_hash or digest(target/'TradingLab/.env')!=env_hash:raise Blocked('配置复制校验未通过。')
        databases=0
        for name in ('TradingLab/data','MarketDataAgent'):
            for p in (target/name).rglob('*'):
                if p.is_file() and p.suffix.lower() in ('.db','.sqlite','.sqlite3'):
                    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
                        db.execute('PRAGMA query_only=ON')
                        if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise Blocked('副本数据库检查失败：'+p.name)
                    databases+=1
        # Exact ephemeral connection descriptors only. No cursor/session/task directory deletion.
        for rel in ('TradingLab/data/runtime/supervisor.json','TradingLab/data/runtime/web-instance.json','MarketDataAgent/connection.json'):
            p=target/rel
            if p.exists():p.unlink()
        (target/'migration-receipt.json').write_text(json.dumps({'status':'COMPLETE','database_count':databases,
            'source_preserved':True,'verified':before,'env_sha256':env_hash,'ephemeral_descriptors_removed':3},ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'MIGRATION_INCOMPLETE').unlink()
        print('完整复制及数据库检查通过：'+str(databases)+' 个数据库。原目录未删除、未重置、未升级。')
        print('请先 Check.cmd；确认仅一个目录承担正式采集，勿并行运行新旧正式账户。')

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='同版本完整离线迁移，不停止来源、不覆盖目标。')
    p.add_argument('--source-core',required=True,type=Path);p.add_argument('--source-agent',required=True,type=Path)
    p.add_argument('--target',required=True,type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:configure();migrate(a.source_core,a.source_agent,a.target,a.apply);return 0
    except Exception as e:
        print('未迁移完成：'+(str(e) if isinstance(e,Blocked) else type(e).__name__+'；原目录保留，新目录若已创建则禁止启动。'));return 1
if __name__=='__main__':raise SystemExit(main())
