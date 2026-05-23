/**
 * 段位视觉：1~6 对应动图 1_1~6_1（低→高）
 */
const TIER_META = [
  { badge: '徒', class: 'tier-1', name: '新锐学徒', image: '/assets/tiers/tier-1.gif' },
  { badge: '手', class: 'tier-2', name: '业余球手', image: '/assets/tiers/tier-2.gif' },
  { badge: '友', class: 'tier-3', name: '资深球友', image: '/assets/tiers/tier-3.gif' },
  { badge: '好', class: 'tier-4', name: '赛场好手', image: '/assets/tiers/tier-4.gif' },
  { badge: '将', class: 'tier-5', name: '实力战将', image: '/assets/tiers/tier-5.gif' },
  { badge: '王', class: 'tier-6', name: '殿堂球王', image: '/assets/tiers/tier-6.gif' },
];

function getTierImage(tierIndex) {
  const i = parseInt(tierIndex, 10);
  const idx = !i || i < 1 ? 0 : Math.min(i - 1, TIER_META.length - 1);
  return TIER_META[idx].image;
}

function getTierStyle(tierIndex) {
  const i = parseInt(tierIndex, 10);
  const idx = !i || i < 1 ? 0 : Math.min(i - 1, TIER_META.length - 1);
  const m = TIER_META[idx];
  return {
    tierClass: m.class,
    tierBadge: m.badge,
    tierName: m.name,
    tierImage: m.image,
    tierIcon: m.image,
  };
}

function getTierIcon(tierIndex) {
  return getTierImage(tierIndex);
}

function decorateTier(item) {
  if (!item) return item;
  const style = getTierStyle(item.tier_index);
  return { ...item, ...style };
}

function withTierIcons(list) {
  return (list || []).map(decorateTier);
}

module.exports = {
  TIER_META,
  getTierImage,
  getTierStyle,
  getTierIcon,
  decorateTier,
  withTierIcons,
};
