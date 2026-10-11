"""Small, immutable Account-owned evidence for retired source contexts."""
import json
from engines.account.ledger import canonical, digest
from contracts.account.portfolio import AccountError


def preserve(repository, account_id, evidence):
    # Validate the account through its owner before creating the evidence file.
    with repository.transaction(account_id) as db:
        repository.events(db)
    path = repository.path(account_id).with_name('retained-context.json')
    value = {'sha256': digest(evidence), 'evidence': evidence}
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise AccountError('RETAINED_EVIDENCE_CONFLICT')
    else:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(canonical(value))
    return read(repository, account_id)


def read(repository, account_id):
    path = repository.path(account_id).with_name('retained-context.json')
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if digest(value['evidence']) != value['sha256']:
        raise AccountError('RETAINED_EVIDENCE_CORRUPT')
    return value['evidence']
