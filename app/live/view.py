from pathlib import Path
from app.shell.registry import Page


def fragment():
    return Path(__file__).with_name('templates').joinpath('live.html').read_text(encoding='utf-8')


def page():
    return Page('实时事件、独立AI观点与影子账户状态。',(),
                content_html=fragment(),styles=('/assets/forms.css','/assets/live.css','/assets/history.css'),scripts=('/assets/reading-format.js','/assets/display-refresh.js','/assets/live.js','/assets/account-binding.js','/assets/history.js','/assets/runtime-center.js'))
