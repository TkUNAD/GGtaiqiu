/** 天梯规则表单：与 Web 总后台 collectLadderBody 对齐 */

const CHALLENGE_FIELDS = [
  { key: 'challenge_rank_min', label: '挑战名次下限' },
  { key: 'challenge_rank_max', label: '挑战名次上限' },
  { key: 'daily_ranked_limit', label: '每日排位上限(场)' },
  { key: 'weekly_ranked_limit', label: '每周排位上限(场)' },
  { key: 'daily_bonus_valid_match', label: '有效局日常加分' },
  { key: 'daily_bonus_break_run', label: '炸清加分' },
  { key: 'daily_bonus_clearance', label: '接清加分' },
  { key: 'daily_bonus_hour_open', label: '开台小时加分' },
  { key: 'bonus_review_threshold', label: '炸清/接清审核阈值' },
  { key: 'cheat_penalty_points', label: '作弊扣分' },
  { key: 'cheat_scroll_times', label: '大屏滚动次数' },
];

const POINT_RULE_FIELDS = [
  { key: 'max_ranked_tier_gap', label: '允许排位最大段位差' },
  { key: 'same_winner_base', label: '同段-胜者基础' },
  { key: 'same_winner_per_frame', label: '同段-胜者每局差分' },
  { key: 'same_loser_base', label: '同段-败者基础' },
  { key: 'same_loser_per_frame', label: '同段-败者每局差分' },
  { key: 'low_win_winner_base', label: '低段胜-胜者基础' },
  { key: 'low_win_winner_per_frame', label: '低段胜-每局差分' },
  { key: 'low_win_loser_base', label: '低段胜-败者基础' },
  { key: 'low_win_loser_per_frame', label: '低段胜-败者每局差分' },
  { key: 'high_win_winner_base', label: '高段胜-胜者基础' },
  { key: 'high_win_winner_per_frame', label: '高段胜-每局差分' },
  { key: 'high_win_loser_base', label: '高段胜-败者基础' },
  { key: 'high_win_loser_per_frame', label: '高段胜-败者每局差分' },
  { key: 'casual_winner_bonus', label: '休闲赛胜者加分' },
];

function num(v, fallback) {
  const n = parseInt(v, 10);
  return Number.isNaN(n) ? fallback : n;
}

function buildFormFromRules(rules, options) {
  const { includeTiers = false, includeIdle = false } = options || {};
  const pr = rules.point_rules || {};
  const sections = [];

  if (includeTiers) {
    const tiers = rules.tier_definitions || [];
    sections.push({
      id: 'tiers',
      title: '六段位名称',
      fields: tiers.map((t, i) => ({
        key: `tier_${i}`,
        label: `第${i + 1}段`,
        value: String((t && t.name) || ''),
        tierIndex: i,
      })),
    });
  }

  sections.push({
    id: 'points',
    title: '选手获得积分规则',
    fields: POINT_RULE_FIELDS.map((f) => ({
      ...f,
      value: String(pr[f.key] != null ? pr[f.key] : ''),
      prKey: f.key,
    })),
  });

  sections.push({
    id: 'challenge',
    title: '挑战与日常规则',
    fields: CHALLENGE_FIELDS.map((f) => ({
      ...f,
      value: String(rules[f.key] != null ? rules[f.key] : ''),
    })),
  });

  if (includeIdle) {
    const alertMin = Math.max(1, Math.round((rules.match_idle_alert_seconds || 600) / 60));
    const promptMin = Math.max(1, Math.round((rules.match_idle_prompt_seconds || 60) / 60));
    sections.push({
      id: 'idle',
      title: '对局闲置与自动结束',
      fields: [
        { key: 'match_idle_alert_min', label: '无操作提醒(分钟)', value: String(alertMin) },
        { key: 'match_idle_prompt_min', label: '提醒后自动结束(分钟)', value: String(promptMin) },
      ],
    });
  }

  return sections;
}

function collectBody(sections, rules, options) {
  const { includeTiers = false, includeIdle = false } = options || {};
  const flat = {};
  (sections || []).forEach((sec) => {
    (sec.fields || []).forEach((f) => {
      flat[f.key] = f.value;
    });
  });

  const pr = { ...(rules.point_rules || {}) };
  POINT_RULE_FIELDS.forEach((def) => {
    const v = flat[def.key];
    if (v !== undefined && v !== '') pr[def.key] = num(v, 0);
  });

  const body = {
    challenge_rank_min: num(flat.challenge_rank_min, rules.challenge_rank_min || 1),
    challenge_rank_max: num(flat.challenge_rank_max, rules.challenge_rank_max || 5),
    daily_ranked_limit: num(flat.daily_ranked_limit, rules.daily_ranked_limit || 0),
    weekly_ranked_limit: num(flat.weekly_ranked_limit, rules.weekly_ranked_limit || 0),
    daily_bonus_valid_match: num(flat.daily_bonus_valid_match, 0),
    daily_bonus_break_run: num(flat.daily_bonus_break_run, 0),
    daily_bonus_clearance: num(flat.daily_bonus_clearance, 0),
    daily_bonus_hour_open: num(flat.daily_bonus_hour_open, 0),
    bonus_review_threshold: num(flat.bonus_review_threshold, 2),
    cheat_penalty_points: num(flat.cheat_penalty_points, 200),
    cheat_scroll_times: num(flat.cheat_scroll_times, 3),
    point_rules: pr,
  };

  if (includeIdle) {
    body.match_idle_alert_seconds = Math.max(60, num(flat.match_idle_alert_min, 10) * 60);
    body.match_idle_prompt_seconds = Math.max(30, num(flat.match_idle_prompt_min, 1) * 60);
  }

  if (includeTiers) {
    const defs = [];
    for (let i = 0; i < 6; i++) {
      defs.push({ name: (flat[`tier_${i}`] || '').trim() || `段位${i + 1}` });
    }
    body.tier_definitions = defs;
  }

  return body;
}

function onFieldInput(sections, key, value) {
  return (sections || []).map((sec) => ({
    ...sec,
    fields: (sec.fields || []).map((f) => (f.key === key ? { ...f, value } : f)),
  }));
}

module.exports = {
  buildFormFromRules,
  collectBody,
  onFieldInput,
  CHALLENGE_FIELDS,
};
