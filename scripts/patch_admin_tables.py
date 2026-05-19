# -*- coding: utf-8 -*-
import os

path = os.path.join(os.path.dirname(__file__), "..", "backend", "templates", "admin.html")
with open(path, "r", encoding="utf-8") as f:
    s = f.read().replace("\r\n", "\n")

old = (
    '      <motion id="tab-tables" class="tab-panel hidden">\n'
    '        <div class="card"><table><thead><tr><th>桌台</th><th>开台状态</th><th>当前对局</th><th>操作</th></tr></thead>\n'
    '          <tbody id="tableTable"></tbody></table></div>\n'
    '      </div>'
).replace("<motion ", "<div ")

new = (
    '      <div id="tab-tables" class="tab-panel hidden">\n'
    '        <div class="card">\n'
    '          <div class="toolbar">\n'
    '            <button onclick="showAddTableForm()">添加台球桌</button>\n'
    '            <button class="secondary" onclick="loadTables()">刷新</button>\n'
    '          </div>\n'
    '          <p style="color:#6B21A8;font-size:13px;margin-bottom:12px">可修改名称、开台/关台；扫码参数 table_id + qr_token</p>\n'
    '          <table><thead><tr><th>编号</th><th>名称</th><th>二维码Token</th><th>开台</th><th>当前对局</th><th>操作</th></tr></thead>\n'
    '          <tbody id="tableTable"></tbody></table>\n'
    '        </div>\n'
    '      </div>'
)

if old not in s:
    raise SystemExit("pattern not found")
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(s.replace(old, new, 1))
print("admin.html patched OK")
