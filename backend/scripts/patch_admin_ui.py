# -*- coding: utf-8 -*-
import pathlib

p = pathlib.Path(__file__).resolve().parents[1] / "templates" / "admin.html"
t = p.read_text(encoding="utf-8")

t = t.replace(
    "        '<motion.div class=\"stat-item\"><strong>' + d.pending_exchanges + '</strong>待审核兑换</motion.div>';",
    "        '<div class=\"stat-item\"><strong>' + (d.pending_bonus_reviews || 0) + '</strong>待审核炸清/接清</div>' +\n"
    "        '<motion.div class=\"stat-item\"><strong>' + d.pending_exchanges + '</strong>待审核兑换</motion.div>';",
)
# fix typo in replacement
t = t.replace("</motion.div>';", "</div>';", 1) if "</motion.div>" in t else t

old_actions = """        const actions = (m.status === 'playing' || m.status === 'pending_review')
          ? '<button onclick="reviewMatch(\\'' + mid + '\\',\\'approve\\')">通过</button> ' +
            '<button class="danger" onclick="reviewMatch(\\'' + mid + '\\',\\'reject\\')">驳回</button>'
          : '-';"""

new_actions = """        let actions = '-';
        if (m.needs_bonus_review && m.bonus_review_queue && m.bonus_review_queue.length) {
          const q = m.bonus_review_queue[0];
          const alert = m.bonus_review_alert ? '<div style="color:#c62828;font-weight:bold;margin-bottom:6px">' + escapeHtml(m.bonus_review_alert) + '</div>' : '';
          actions = alert +
            '<button onclick="bonusReview(\\'' + mid + '\\',\\'' + q.bonus_id + '\\',\\'' + q.user_id + '\\',\\'approve\\')">审核通过加分</button> ' +
            '<button onclick="bonusReview(\\'' + mid + '\\',\\'' + q.bonus_id + '\\',\\'' + q.user_id + '\\',\\'reject\\')">驳回</button> ' +
            '<button class="danger" onclick="bonusReview(\\'' + mid + '\\',\\'' + q.bonus_id + '\\',\\'' + q.user_id + '\\',\\'cheat\\')">认定作弊</button>';
        } else if (m.status === 'playing' || m.status === 'pending_review') {
          actions = '<button onclick="reviewMatch(\\'' + mid + '\\',\\'approve\\')">通过</button> ' +
            '<button class="danger" onclick="reviewMatch(\\'' + mid + '\\',\\'reject\\')">驳回</button>';
        }"""

if old_actions in t:
    t = t.replace(old_actions, new_actions)
    print("actions ok")
else:
    print("actions miss")

review_fn = """
    async function bonusReview(matchId, bonusId, userId, action) {
      const note = prompt('备注(可选)') || '';
      if (action === 'cheat' && !confirm('认定作弊将扣除积分并在大屏滚动公示，确定？')) return;
      try {
        await api('/api/admin/match/' + matchId + '/bonus-review', {
          method: 'POST',
          body: { action, bonus_id: bonusId, user_id: userId, note }
        });
        alert(action === 'approve' ? '已通过并加分' : action === 'cheat' ? '已处罚并公示' : '已驳回');
        loadMatches();
        loadDashboard();
      } catch (e) { alert(e.message); }
    }

"""

if "async function bonusReview" not in t:
    t = t.replace("    async function reviewMatch(id, action) {", review_fn + "    async function reviewMatch(id, action) {")
    print("bonusReview fn ok")

ladder_load = """      document.getElementById('lr_bonus_hour').value = r.daily_bonus_hour_open;
      document.getElementById('lr_rule_hint').textContent = r.challenge_rank_min + '~' + r.challenge_rank_max;"""

ladder_load_new = """      document.getElementById('lr_bonus_hour').value = r.daily_bonus_hour_open;
      document.getElementById('lr_bonus_review').value = r.bonus_review_threshold || 2;
      document.getElementById('lr_cheat_penalty').value = r.cheat_penalty_points || 200;
      document.getElementById('lr_cheat_scroll').value = r.cheat_scroll_times || 3;
      document.getElementById('lr_rule_hint').textContent = r.challenge_rank_min + '~' + r.challenge_rank_max;"""

if ladder_load in t:
    t = t.replace(ladder_load, ladder_load_new)
    print("ladder load ok")

ladder_save = """          daily_bonus_hour_open: parseInt(document.getElementById('lr_bonus_hour').value, 10),
        }});"""

ladder_save_new = """          daily_bonus_hour_open: parseInt(document.getElementById('lr_bonus_hour').value, 10),
          bonus_review_threshold: parseInt(document.getElementById('lr_bonus_review').value, 10),
          cheat_penalty_points: parseInt(document.getElementById('lr_cheat_penalty').value, 10),
          cheat_scroll_times: parseInt(document.getElementById('lr_cheat_scroll').value, 10),
        }});"""

if ladder_save in t:
    t = t.replace(ladder_save, ladder_save_new)
    print("ladder save ok")

# dashboard - simple line insert
needle = "        '<div class=\"stat-item\"><strong>' + d.matches_count + '</strong>总对局</div>' +\n"
insert = needle + "        '<div class=\"stat-item\"><strong>' + (d.pending_bonus_reviews || 0) + '</strong>待审核炸清/接清</div>' +\n"
if insert not in t and needle in t:
    t = t.replace(needle, insert)
    print("dashboard ok")

p.write_text(t, encoding="utf-8")
print("done")
