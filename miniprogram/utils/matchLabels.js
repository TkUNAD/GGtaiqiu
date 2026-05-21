const MATCH_STATUS_LABELS = {
  playing: '进行中',
  finished: '已结束',
  invalid: '无效',
  cancelled: '已取消',
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  modified: '已改判',
};

const MATCH_TYPE_LABELS = {
  ranked: '排位',
  casual: '休闲',
};

function matchStatusLabel(status) {
  return MATCH_STATUS_LABELS[status] || status || '未知';
}

function matchTypeLabel(type) {
  return MATCH_TYPE_LABELS[type] || type || '休闲';
}

module.exports = { matchStatusLabel, matchTypeLabel, MATCH_STATUS_LABELS };
