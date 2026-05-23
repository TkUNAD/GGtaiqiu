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
    rankIcon: getRankIcon(item.rank || item.club_rank),
    tierIcon: getTierIcon(item.tier_index),
  }));
}

function decorateList(list) {
  return withRankIcons(withTierIcons(list));
}

module.exports = {
  RANK_ICONS,
  getRankIcon,
  withRankIcons,
  decorateList,
  getTierIcon,
  withTierIcons,
};
