"""Process lease for one service writer per configured data directory."""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def runtime_lease(data_root):
    path=Path(data_root)/'runtime'/'service.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if path.stat().st_size==0:handle.write(b'0');handle.flush()
        # Lock well beyond EOF (including buffered read-ahead). Windows byte locks otherwise
        # prohibit read-only hash audits of the marker itself.
        handle.seek(1 << 30)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('TRADING_LAB_ALREADY_RUNNING: another service owns this data directory; stop it before restarting, even on a different port.') from None
        try:yield
        finally:
            handle.seek(1 << 30)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
