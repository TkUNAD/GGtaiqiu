# -*- coding: utf-8 -*-
import os
import re

path = os.path.join(os.path.dirname(__file__), "..", "backend", "templates", "admin.html")
with open(path, "r", encoding="utf-8") as f:
    s = f.read().replace("\r\n", "\n")

s = s.replace("<motion class=", "<motion class=").replace("<motion ", "<div ")
s = s.replace("</motion>", "</div>")
s = s.replace('</motion></td>', '</motion></td>').replace("</motion></td>", "</div></td>")

old_load = """    async function loadTables() {
      const list = await api('/api/admin/tables');
      _tablesCache = list;
      document.getElementById('tableTable').innerHTML = list.map(t => {
        const link = (t.qr_link || '').replace(/</g, '');
        const short = link.length > 36 ? link.slice(0, 36) + '...' : link;
        return '<tr><td>' + t.id + '</td><td>' + t.name + '</td>' +
          '<td title="' + link + '"><code style="font-size:11px">' + short + '</code></td>' +
          '<td>' + (t.opened ? '<span class="badge badge-green">已开台</span>' : '<span class="badge badge-yellow">未开台</span>') +
          '</td><td>' + (t.current_match_id || '-') + '</td><td><div class="btn-group">' +
          '<button onclick="showTableQr(\\'' + t.id + '\\')">二维码</button>' +
          '<button onclick="editTableName(\\'' + t.id + '\\',\\'' + t.name.replace(/'/g, "\\\\'") + '\\')">改名</button> ' +
          (t.opened ? '<button class="secondary" onclick="toggleTable(\\'' + t.id + '\\',false)">关台</button>' :
            '<button onclick="toggleTable(\\'' + t.id + '\\',true)">开台</button>') +
          '<button class="danger" onclick="deleteTable(\\'' + t.id + '\\')">删除</button></div></td></tr>';
      }).join('');
    }"""

new_load = r"""    async function loadTables() {
      const tbody = document.getElementById('tableTable');
      try {
        const list = await api('/api/admin/tables');
        _tablesCache = list;
        if (!list || !list.length) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align:center">暂无桌台</td></tr>';
          return;
        }
        tbody.innerHTML = list.map(t => {
          const link = t.qr_link || tableDefaultLink(t);
          const short = link.length > 32 ? link.slice(0, 32) + '...' : link;
          const tid = escapeHtml(t.id);
          const qrSrc = API + '/api/admin/table/' + encodeURIComponent(t.id) + '/qrcode.png?t=' + Date.now();
          return '<tr>' +
            '<td><img class="qr-thumb" src="' + qrSrc + '" alt="QR" onclick="showTableQr(\'' + tid + '\')"></td>' +
            '<td>' + tid + '</td><td>' + escapeHtml(t.name) + '</td>' +
            '<td title="' + escapeHtml(link) + '"><code style="font-size:11px">' + escapeHtml(short) + '</code></td>' +
            '<td>' + (t.opened ? '<span class="badge badge-green">已开台</span>' : '<span class="badge badge-yellow">未开台</span>') +
            '</td><td>' + escapeHtml(t.current_match_id || '-') + '</td>' +
            '<td><div class="btn-group">' +
            '<button onclick="showTableQr(\'' + tid + '\')">二维码</button>' +
            '<button onclick="editTableName(\'' + tid + '\')">改名</button>' +
            (t.opened ? '<button class="secondary" onclick="toggleTable(\'' + tid + '\',false)">关台</button>' :
              '<button onclick="toggleTable(\'' + tid + '\',true)">开台</button>') +
            '<button class="danger" onclick="deleteTable(\'' + tid + '\')">删除</button></div></td></tr>';
        }).join('');
      } catch (e) {
        tbody.innerHTML = '<tr><td colspan="7" style="color:red;padding:12px">加载失败: ' + escapeHtml(e.message) +
          '<br>请重启 run.bat 并执行: pip install qrcode[pil]</td></tr>';
      }
    }"""

if old_load not in s:
    raise SystemExit("loadTables block not found")
s = s.replace(old_load, new_load)

old_show = re.search(r"    function showTableQr\(id\) \{.*?    function renderQrCanvas", s, re.S)
if not old_show:
    raise SystemExit("showTableQr block not found")

new_show = r"""    function qrImageUrl(id, text) {
      let url = API + '/api/admin/table/' + encodeURIComponent(id) + '/qrcode.png?t=' + Date.now();
      if (text) url += '&text=' + encodeURIComponent(text);
      return url;
    }

    function refreshModalQr(id) {
      const text = document.getElementById('qrLinkInput').value.trim();
      const img = document.getElementById('qrImg');
      if (img) img.src = qrImageUrl(id, text);
      const prev = document.getElementById('qrLinkPreview');
      if (prev) prev.textContent = text;
    }

    function showTableQr(id) {
      const t = _tablesCache.find(x => x.id === id);
      if (!t) { alert('请先点击刷新'); return; }
      const link = t.qr_link || tableDefaultLink(t);
      document.getElementById('modal').classList.remove('hidden');
      document.getElementById('modalContent').innerHTML =
        '<div class="modal-box wide">' +
        '<h3>' + escapeHtml(t.name) + '（' + escapeHtml(t.id) + '）二维码</h3>' +
        '<motion class="qr-wrap"><img id="qrImg" style="width:220px;height:220px" src="' + qrImageUrl(id) + '"></div>' +
        '<p class="qr-label">扫码链接</p><input id="qrLinkInput" value="' + escapeHtml(link) + '">' +
        '<p class="qr-label">Token</p><input id="qrTokenInput" value="' + escapeHtml(t.qr_token || '') + '">' +
        '<div class="link-preview" id="qrLinkPreview">' + escapeHtml(link) + '</div>' +
        '<div class="qr-actions">' +
        '<button onclick="saveTableQr(\'' + escapeHtml(id) + '\')">保存</button>' +
        '<button class="secondary" onclick="copyQrLink()">复制</button>' +
        '<button class="secondary" onclick="downloadQrImageServer(\'' + escapeHtml(id) + '\')">下载</button>' +
        '<button class="secondary" onclick="resetTableQrLink(\'' + escapeHtml(id) + '\')">默认</button>' +
        '<button class="secondary" onclick="closeModal()">关闭</button></div></motion>';
      document.getElementById('qrLinkInput').onblur = function() { refreshModalQr(id); };
    }

    function renderQrCanvas"""

s = s[: old_show.start()] + new_show + s[old_show.end() :]
s = s.replace("<motion class=", "<div class=").replace("</motion>", "</div>")

with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(s)
print("patched admin.html OK")
