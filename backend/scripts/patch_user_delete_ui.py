# -*- coding: utf-8 -*-
import pathlib

p = pathlib.Path(__file__).resolve().parents[1] / "templates" / "admin.html"
t = p.read_text(encoding="utf-8")

old_tab = """      <motion.div id="tab-users" class="tab-panel hidden">
        <div class="card"><table><thead><tr><th>昵称</th><th>手机</th><th>积分</th><th>段位</th><th>排名</th><th>胜/负</th><th>状态</th><th>操作</th></tr></thead>
          <tbody id="userTable"></tbody></table></div>
      </div>"""

old_tab = old_tab.replace("motion.div", "motion.div")  # noop
old_tab = """      <div id="tab-users" class="tab-panel hidden">
        <div class="card"><table><thead><tr><th>昵称</th><th>手机</th><th>积分</th><th>段位</th><th>排名</th><th>胜/负</th><th>状态</th><th>操作</th></tr></thead>
          <tbody id="userTable"></tbody></table></motion.div>
      </div>""".replace("motion.div", "div")

new_tab = """      <div id="tab-users" class="tab-panel hidden">
        <div class="card">
          <div class="toolbar">
            <button class="secondary" onclick="loadUsers()">刷新</button>
            <button class="danger" onclick="batchDeleteUsers()">批量删除</button>
            <span id="userSelectHint" style="font-size:13px;color:#666;align-self:center"></span>
          </div>
          <div class="table-scroll">
          <table><thead><tr>
            <th style="width:40px"><input type="checkbox" id="userSelectAll" title="全选" onchange="toggleAllUsers(this)"></th>
            <th>昵称</th><th>手机</th><th>积分</th><th>段位</th><th>排名</th><th>胜/负</th><th>状态</th><th>状态</th><th>操作</th>
          </tr></thead>
          <tbody id="userTable"></tbody></table>
          </div>
        </div>
      </div>"""

# fix duplicate 状态 in new_tab
new_tab = new_tab.replace("<th>状态</th><th>状态</th>", "<th>状态</th>")

if old_tab not in t:
    # try CRLF
    old_tab_crlf = old_tab.replace("\n", "\r\n")
    new_tab_crlf = new_tab.replace("\n", "\r\n")
    if old_tab_crlf in t:
        t = t.replace(old_tab_crlf, new_tab_crlf)
        print("tab crlf ok")
    else:
        print("tab miss")
        idx = t.find("tab-users")
        print(repr(t[idx:idx+200]))
else:
    t = t.replace(old_tab, new_tab)
    print("tab ok")

old_load = """    async function loadUsers() {
      const list = await api('/api/admin/users');
      document.getElementById('userTable').innerHTML = list.map(u =>
        '<tr><td>' + u.nickname + '</td><td>' + (u.phone || '-') + '</td><td>' + u.score + '</td>' +
        '<td>' + (u.tier ? u.tier.tier_name : '') + '</td><td>' + u.rank + '</td><td>' + u.wins + '/' + u.losses + '</td>' +
        '<td>' + (u.status === 'banned' ? '<span class="badge badge-red">封禁</span>' : '<span class="badge badge-green">正常</span>') + '</td>' +
        '<td><button onclick="adjustScore(\\'' + u.id + '\\')">调分</button> ' +
        (u.status === 'banned' ? '<button onclick="punish(\\'' + u.id + '\\',\\'unban\\')">解封</button>' :
          '<button class="danger" onclick="punish(\\'' + u.id + '\\',\\'ban\\')">封禁</button> ' +
          '<button class="danger" onclick="punish(\\'' + u.id + '\\',\\'reset_score\\')">清零</button>') + '</td></tr>'
      ).join('');
    }"""

new_load = """    function getSelectedUserIds() {
      return Array.from(document.querySelectorAll('.user-cb:checked')).map(function(cb) { return cb.dataset.id; });
    }

    function updateUserSelectHint() {
      var n = getSelectedUserIds().length;
      var hint = document.getElementById('userSelectHint');
      if (hint) hint.textContent = n ? ('已选 ' + n + ' 人') : '';
      var all = document.querySelectorAll('.user-cb');
      var sel = document.querySelectorAll('.user-cb:checked');
      var sa = document.getElementById('userSelectAll');
      if (sa && all.length) sa.checked = sel.length === all.length;
    }

    function toggleAllUsers(el) {
      document.querySelectorAll('.user-cb').forEach(function(cb) { cb.checked = el.checked; });
      updateUserSelectHint();
    }

    async function loadUsers() {
      const list = await api('/api/admin/users');
      document.getElementById('userTable').innerHTML = list.map(function(u) {
        var uid = escapeHtml(u.id);
        var status = u.status === 'banned'
          ? '<span class="badge badge-red">封禁</span>'
          : '<span class="badge badge-green">正常</span>';
        var ops = '<div class="btn-group">' +
          '<button onclick="adjustScore(\\'' + uid + '\\')">调分</button> ';
        if (u.status === 'banned') {
          ops += '<button onclick="punish(\\'' + uid + '\\',\\'unban\\')">解封</button> ';
        } else {
          ops += '<button class="danger" onclick="punish(\\'' + uid + '\\',\\'ban\\')">封禁</button> ' +
            '<button class="danger" onclick="punish(\\'' + uid + '\\',\\'reset_score\\')">清零</button> ';
        }
        ops += '<button class="danger" onclick="deleteUser(\\'' + uid + '\\')">删除</button></div>';
        return '<tr><td><input type="checkbox" class="user-cb" data-id="' + uid + '" onchange="updateUserSelectHint()"></td>' +
          '<td>' + escapeHtml(u.nickname) + '</td><td>' + escapeHtml(u.phone || '-') + '</td><td>' + u.score + '</td>' +
          '<td>' + escapeHtml(u.tier ? u.tier.tier_name : '') + '</td><td>' + u.rank + '</td>' +
          '<td>' + u.wins + '/' + u.losses + '</td><td>' + status + '</td><td>' + ops + '</td></tr>';
      }).join('');
      updateUserSelectHint();
    }

    async function deleteUser(uid) {
      if (!confirm('确定删除该玩家？删除后不可恢复（历史对局记录保留）。')) return;
      try {
        await api('/api/admin/user/' + uid, { method: 'DELETE' });
        alert('已删除');
        loadUsers();
      } catch (e) { alert(e.message); }
    }

    async function batchDeleteUsers() {
      var ids = getSelectedUserIds();
      if (!ids.length) { alert('请先勾选要删除的玩家'); return; }
      if (!confirm('确定删除选中的 ' + ids.length + ' 名玩家？删除后不可恢复。')) return;
      try {
        var r = await api('/api/admin/users/batch-delete', { method: 'POST', body: { user_ids: ids } });
        alert('已删除 ' + (r.deleted || ids.length) + ' 名玩家');
        loadUsers();
      } catch (e) { alert(e.message); }
    }"""

for old, new in [(old_load, new_load)]:
    if old in t:
        t = t.replace(old, new)
        print("load ok")
    else:
        old_crlf = old.replace("\n", "\r\n")
        new_crlf = new.replace("\n", "\r\n")
        if old_crlf in t:
            t = t.replace(old_crlf, new_crlf)
            print("load crlf ok")
        else:
            print("load miss")

p.write_text(t, encoding="utf-8")
print("done")
