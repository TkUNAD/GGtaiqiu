const { getTierIcon, withTierIcons } = require('./tierIcons');

/** 天梯前五名次图标 */
const RANK_ICONS = {
  1: '🥇',
  2: '🥈',
  3: '🥉',
  4: '4️⃣',
  5: '5️⃣',
};

function getRankIcon(rank) {
  const r = parseInt(rank, 10);
  return RANK_ICONS[r] || '';
}

function withRankIcons(list) {
  return (list || []).map((item) => ({
    ...item,
    rankIcon: getRankIcon(item.club_rank || item.rank),
    tierIcon: getTierIcon(item.tier_index),
  }));
}

function decorateList(list) {
  return withRankIcons(withTierIcons(list));
}

/** 排行榜前 N 名固定占位，不足显示空位 */
function padLeaderboardTop(list, count, rankKey) {
  const key = rankKey || 'club_rank';
  const by = {};
  const rest = [];
  (list || []).forEach((item) => {
    const r = parseInt(item[key] || item.rank, 10);
    if (r >= 1 && r <= count) by[r] = item;
    else rest.push(item);
  });
  const top = [];
  for (let i = 1; i <= count; i += 1) {
    if (by[i]) {
      top.push({ ...by[i], empty: false, displayRank: i, rowKey: by[i].id || `r-${i}` });
    } else {
      top.push({ empty: true, displayRank: i, [key]: i, rowKey: `empty-${i}` });
    }
  }
  rest.sort((a, b) => {
    const ra = parseInt(a[key] || a.rank, 10) || 9999;
    const rb = parseInt(b[key] || b.rank, 10) || 9999;
    return ra - rb;
  });
  return [
    ...top,
    ...rest.map((item) => ({
      ...item,
      empty: false,
      rowKey: item.id || `r-${item[key] || item.rank}`,
    })),
  ];
}

/** 可挑战玩家固定槽位（高 rmin~rmax 名），无选手时留空 */
function buildChallengeSlots(targets, myRank, opts) {
  const rmin = (opts && opts.rmin) || 1;
  const rmax = (opts && opts.rmax) || 5;
  const mr = parseInt(myRank, 10);
  const byRank = {};
  decorateList(targets || []).forEach((t) => {
    if (t && t.rank != null) byRank[t.rank] = t;
  });
  const slots = [];
  for (let gap = rmin; gap <= rmax; gap += 1) {
    const targetRank = mr - gap;
    if (mr >= 9999 || targetRank < 1) {
      slots.push({
        empty: true,
        gap,
        slotLabel: `高 ${gap} 名`,
        slotHint: mr >= 9999 ? '暂无排名' : '暂无该名次',
      });
      continue;
    }
    const player = byRank[targetRank];
    if (player) {
      slots.push({
        ...player,
        empty: false,
        gap,
        targetRank,
        slotLabel: `第 ${targetRank} 名`,
      });
    } else {
      slots.push({
        empty: true,
        gap,
        targetRank,
        slotLabel: `第 ${targetRank} 名`,
        slotHint: '虚位以待',
      });
    }
  }
  return slots;
}

module.exports = {
  RANK_ICONS,
  getRankIcon,
  withRankIcons,
  decorateList,
  padLeaderboardTop,
  buildChallengeSlots,
  getTierIcon,
  withTierIcons,
};
