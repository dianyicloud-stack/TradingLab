from app.shell.registry import Module
from app.account.view import page
def create_module(health):
    return Module('account','Account','/account','影子账户',health,page)
