# -*- coding: utf-8 -*-
import pathlib
import re

p = pathlib.Path(__file__).resolve().parents[1] / "templates" / "admin.html"
t = p.read_text(encoding="utf-8")

# toolbar buttons
old_toolbar = """          <motion.div class="toolbar">
            <button class="secondary" onclick="loadUsers()">刷新</button>
            <button class="danger" onclick="batchDeleteUsers()">批量删除</button>
            <span id="userSelectHint" style="font-size:13px;color:#666;align-self:center"></span>
          </div>"""
old_toolbar = old_toolbar.replace("motion.div", "div")
new_toolbar = """          <div class="toolbar">
            <button type="button" class="secondary" onclick="loadUsers()">刷新</button>
            <button type="button" class="danger" onclick="batchDeleteUsers()">批量删除</button>
            <button type="button" class="danger" onclick="resetAllData()" id="btnResetAll" style="display:none">重置全部数据</button>
            <span id="userSelectHint" style="font-size:13px;color:#666;align-self:center"></span>
          </div>"""
if old_toolbar in t:
    t = t.replace(old_toolbar, new_toolbar)
    print("toolbar ok")
else:
    t2 = t.replace(
        '<button class="secondary" onclick="loadUsers()">刷新</button>\n            <button class="danger" onclick="batchDeleteUsers()">批量删除</button>',
        '<button type="button" class="secondary" onclick="loadUsers()">刷新</button>\n            <button type="button" class="danger" onclick="batchDeleteUsers()">批量删除</button>\n            <button type="button" class="danger" onclick="resetAllData()" id="btnResetAll" style="display:none">重置全部数据</button>',
    )
    print("toolbar partial", "ok" if "btnResetAll" in t2 else "fail")
    t = t2

new_js = r'''
    function attrEsc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }

    var _userTableBound = false;

    function bindUserTableEvents() {
      var tbody = document.getElementById('userTable');
      if (!tbody || _userTableBound) return;
      _userTableBound = true;
      tbody.addEventListener('click', function(e) {
        var btn = e.target.closest('[data-act]');
        if (!btn || !btn.dataset.uid) return;
        var uid = btn.dataset.uid;
        var act = btn.dataset.act;
        if (act === 'delete') deleteUser(uid);
        else if (act === 'adjust') adjustScore(uid);
        else if (act === 'ban') punish(uid, 'ban');
        else if (act === 'unban') punish(uid, 'unban');
        else if (act === 'reset') punish(uid, 'reset_score');
      });
    }

    function getSelectedUserIds() {
      return Array.from(document.querySelectorAll('.user-cb:checked')).map(function(cb) {
        return cb.getAttribute('data-id');
      }).filter(Boolean);
    }

    function updateUserSelectHint() {
      var n = getSelectedUserIds().length;
      var hint = document.getElementById('userSelectHint');
      if (hint && !hint.dataset.tip) hint.textContent = n ? ('已选 ' + n + ' 人') : '';
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
      try {
        var list = await api('/api/admin/users');
        document.getElementById('userTable').innerHTML = list.map(function(u) {
          var uid = attrEsc(u.id);
          var status = u.status === 'banned'
            ? '<span class="badge badge-red">封禁</span>'
            : '<span class="badge badge-green">正常</span>';
          var ops = '<div class="btn-group">';
          ops += '<button type="button" data-act="adjust" data-uid="' + uid + '">调分</button> ';
          if (u.status === 'banned') {
            ops += '<button type="button" data-act="unban" data-uid="' + uid + '">解封</button> ';
          } else {
            ops += '<button type="button" class="danger" data-act="ban" data-uid="' + uid + '">封禁</button> ';
            ops += '<button type="button" data-act="reset" data-uid="' + uid + '">重置积分</button> ';
          }
          ops += '<button type="button" class="danger" data-act="delete" data-uid="' + uid + '">删除</button></div>';
          return '<tr><td><input type="checkbox" class="user-cb" data-id="' + uid + '"></td>' +
            '<td>' + escapeHtml(u.nickname) + '</td><td>' + escapeHtml(u.phone || '-') + '</td><td>' + (u.score != null ? u.score : 0) + '</td>' +
            '<td>' + escapeHtml(u.tier ? u.tier.tier_name : '') + '</td><td>' + u.rank + '</td>' +
            '<td>' + u.wins + '/' + u.losses + '</td><td>' + status + '</td><td>' + ops + '</td></tr>';
        }).join('');
        updateUserSelectHint();
      } catch (e) {
        alert('加载玩家失败: ' + (e.message || e));
      }
    }

    async function refreshUsersAfterDelete(tip) {
      var sa = document.getElementById('userSelectAll');
      if (sa) sa.checked = false;
      await loadUsers();
      try { await loadDashboard(); } catch (e) { /* ignore */ }
      if (tip) {
        var hint = document.getElementById('userSelectHint');
        if (hint) {
          hint.dataset.tip = '1';
          hint.textContent = tip;
          hint.style.color = '#2e7d32';
          setTimeout(function() {
            delete hint.dataset.tip;
            hint.style.color = '#666';
            updateUserSelectHint();
          }, 2500);
        }
      }
    }

    async function deleteUser(uid) {
      if (!uid) return;
      if (!confirm('确定删除该玩家？删除后不可恢复（历史对局记录保留）。')) return;
      try {
        await api('/api/admin/user/' + encodeURIComponent(uid), { method: 'DELETE' });
        await refreshUsersAfterDelete('已删除，列表已刷新');
      } catch (e) { alert(e.message || String(e)); }
    }

    async function batchDeleteUsers() {
      var ids = getSelectedUserIds();
      if (!ids.length) { alert('请先勾选要删除的玩家'); return; }
      if (!confirm('确定删除选中的 ' + ids.length + ' 名玩家？删除后不可恢复。')) return;
      try {
        var r = await api('/api/admin/users/batch-delete', { method: 'POST', body: { user_ids: ids } });
        await refreshUsersAfterDelete('已删除 ' + (r.deleted || ids.length) + ' 人，列表已刷新');
      } catch (e) { alert(e.message || String(e)); }
    }

    function adjustScore(uid) {
      var delta = prompt('调整积分(正数增加，负数减少)');
      if (delta === null || delta === '') return;
      var n = parseInt(delta, 10);
      if (isNaN(n)) { alert('请输入整数'); return; }
      api('/api/admin/user/' + encodeURIComponent(uid) + '/score', { method: 'POST', body: { delta: n, reason: '管理员调整' } })
        .then(function() { loadUsers(); alert('已调整'); })
        .catch(function(e) { alert(e.message || e); });
    }

    function punish(uid, action) {
      var reason = prompt('原因', action === 'reset_score' ? '管理员重置积分' : '违规处理');
      if (reason === null) return;
      api('/api/admin/user/' + encodeURIComponent(uid) + '/punish', { method: 'POST', body: { action: action, reason: reason, public: true } })
        .then(function() { loadUsers(); alert(action === 'reset_score' ? '已重置为初始积分1000' : '操作成功'); })
        .catch(function(e) { alert(e.message || e); });
    }

    async function resetAllData() {
      if (!adminSession || adminSession.role !== 'super') {
        alert('仅总管理员可重置全部数据');
        return;
      }
      if (!confirm('危险操作：将清空所有玩家、对局、积分日志等数据，是否继续？')) return;
      var username = prompt('请输入总管理员登录账号');
      if (username === null || !username.trim()) return;
      var password = prompt('请输入登录密码');
      if (password === null) return;
      if (!confirm('最后确认：确定重置全部数据？此操作不可恢复！')) return;
      try {
        await api('/api/admin/system/reset', { method: 'POST', body: { username: username.trim(), password: password } });
        alert('全部数据已重置');
        loadDashboard();
        loadUsers();
        loadMatches();
        loadTables();
      } catch (e) { alert(e.message || String(e)); }
    }
'''
new_js = new_js.replace("motion.div", "div")

# Replace block from function bindUserTableEvents through function punish ... until loadTables
pattern = r"    function bindUserTableEvents\(\)[\s\S]*?    function punish\(uid, action\) \{[\s\S]*?\.then\(loadUsers\);\n    \}\n\n    async function loadTables"
if re.search(pattern, t):
    t = re.sub(pattern, new_js.strip() + "\n\n    async function loadTables", t, count=1)
    print("js block ok")
else:
    print("js pattern miss")

# Show reset button for super admin
if "btnResetAll" in t and "applyAdminSession" in t:
    old_apply = "      document.getElementById('ladderPermTip').style.display = canLadder ? 'none' : 'block';"
    new_apply = old_apply + "\n      var btnReset = document.getElementById('btnResetAll');\n      if (btnReset) btnReset.style.display = adminSession.role === 'super' ? '' : 'none';"
    if old_apply in t and "btnResetAll" not in t.split("applyAdminSession")[1][:500]:
        t = t.replace(old_apply, new_apply)
        print("applyAdminSession ok")

# bind on switch tab users
if "if (tab === 'users') loadUsers();" in t and "bindUserTableEvents();" not in t:
    t = t.replace(
        "if (tab === 'users') loadUsers();",
        "if (tab === 'users') { bindUserTableEvents(); loadUsers(); }",
    )
    print("switchTab ok")

# Improve api error when not json
old_api = """    async function api(url, opts = {}) {
      const res = await fetch(API + url, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
        ...opts,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
      const data = await res.json();
      if (data.code !== 0) throw new Error(data.msg);
      return data.data;
    }"""
new_api = """    async function api(url, opts = {}) {
      const method = (opts.method || 'GET').toUpperCase();
      const res = await fetch(API + url, {
        credentials: 'include',
        method: method,
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
        body: opts.body != null ? JSON.stringify(opts.body) : undefined,
      });
      var data;
      try {
        data = await res.json();
      } catch (e) {
        throw new Error('服务器响应异常(' + res.status + ')');
      }
      if (data.code !== 0) throw new Error(data.msg || '请求失败');
      return data.data;
    }"""
if old_api in t:
    t = t.replace(old_api, new_api)
    print("api ok")

p.write_text(t, encoding="utf-8")
print("done")
