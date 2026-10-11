"""Generic HTML rendering. All module-provided strings are escaped."""
from html import escape
from pathlib import Path

CSS = Path(__file__).with_name("static").joinpath("shell.css").read_bytes()


def render_page(registry, module):
    page = module.page()
    health = module.health()
    nav = []
    for index, item in enumerate(registry.modules, 1):
        if item.enabled:
            active = ' aria-current="page" class="active"' if item.id == module.id else ""
            nav.append(f'<a href="{escape(item.route)}"{active}><span class="nav-index">{index:02}</span><span>{escape(item.name)}<small>{escape(item.subtitle)}</small></span></a>')
    cards = "".join(f'<section class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></section>' for label, value in page.cards)
    rows = "".join(f'<tr><th scope="row">{escape(label)}</th><td><span class="badge">{escape(status)}</span></td><td>{escape(detail)}</td></tr>' for label, status, detail in page.rows)
    styles = ''.join(f'<link rel="stylesheet" href="{escape(url)}">' for url in page.styles)
    scripts = ''.join(f'<script defer src="{escape(url)}"></script>' for url in page.scripts)
    body = page.content_html or f'<section class="panel"><div class="panel-title"><h2>模块状态与边界</h2><span>FOUNDATION v0.1</span></div><div class="table-wrap"><table><thead><tr><th>组件 / 数据</th><th>状态 / 归属</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(module.name)} · Trading Lab</title><link rel="stylesheet" href="/assets/shell.css">{styles}{scripts}</head>
<body><a class="skip" href="#main">跳转到内容</a><aside class="sidebar">
<a class="brand" href="/system"><span class="brand-icon">TL</span><span>Trading Lab<small>量价研究工作台</small></span></a>
<div class="nav-caption">WORKSPACE</div><nav aria-label="主导航">{''.join(nav)}</nav>
<div class="sidebar-footer"><span class="dot"></span> LOCAL WORKSPACE<small>Foundation v0.1</small></div></aside>
<div class="workspace"><header class="topbar"><span>Trading Lab <span class="divider">/</span> {escape(module.name)}</span><span class="local-tag">LOCAL · 127.0.0.1</span></header>
<main id="main"><div class="eyebrow">TRADING LAB FOUNDATION</div><div class="title-row"><h1>{escape(module.name)} <span>{escape(module.subtitle)}</span></h1><span class="badge status">{escape(health.status)}</span></div>
<p class="intro">{escape(page.summary)}</p><div class="cards">{cards}</div>
{body}
<p class="note"><span>当前阶段</span>{escape(page.note)}</p>
<footer>Unified UI <span>·</span> Modular Monolith <span>·</span> Domain-owned Storage <span>·</span> Contract-based Integration</footer>
</main></div></body></html>'''.encode("utf-8")
