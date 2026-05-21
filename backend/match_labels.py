"""对局/积分展示用中文标签"""
from typing import Dict, Optional

MATCH_STATUS_LABELS = {
    "playing": "进行中",
    "finished": "已结束",
    "invalid": "无效",
    "cancelled": "已取消",
    "pending_review": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
    "modified": "已改判",
}

MATCH_TYPE_LABELS = {
    "ranked": "排位",
    "casual": "休闲",
}

EXCHANGE_STATUS_LABELS = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已拒绝",
}


def match_status_label(status: str) -> str:
    return MATCH_STATUS_LABELS.get(status or "", status or "未知")


def match_type_label(match_type: str) -> str:
    return MATCH_TYPE_LABELS.get(match_type or "", match_type or "休闲")


def exchange_status_label(status: str) -> str:
    return EXCHANGE_STATUS_LABELS.get(status or "", status or "未知")
