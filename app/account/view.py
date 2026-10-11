from pathlib import Path
from app.shell.registry import Page
TEMPLATE = Path(__file__).with_name('templates').joinpath('account.html').read_text(encoding='utf-8')
def page():
    return Page('用户组合账户 · 共享资金、目标仓位与风险约束。',(),
                content_html=TEMPLATE,styles=('/assets/forms.css',),scripts=('/assets/account.js',))
