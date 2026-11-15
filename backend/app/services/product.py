"""数据产品定义业务规则：状态流转、字段校验与筛选口径都收在这里。

状态机按前置状态校验：发布只接受草稿/开发中/已下线（已下线产品可重新发布恢复可分发），
下架只接受已发布，删除只接受已下线。动作在模块锁内完成状态推进。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "product"
REQUIRED_FIELDS = ["产品编号", "产品名称", "产品类型"]
EDITABLE_FIELDS = ["产品名称", "产品类型", "数据来源", "计算逻辑", "输出格式", "负责人"]
STATUS_ORDER = ["草稿", "开发中", "已发布", "已下线", "已删除"]
# 动作 → (允许的前置状态集合, 目标状态)。
ACTION_RULES: dict[str, tuple[tuple[str, ...], str]] = {
    # 已下线产品重新发布即「恢复可分发」，市场商品随后才能上架。
    "发布产品": (("草稿", "开发中", "已下线"), "已发布"),
    "下线产品": (("已发布",), "已下线"),
    "删除产品": (("已下线",), "已删除"),
}
NEGATIVE_ACTIONS = ["下线产品"]


class ProductService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("产品编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in EDITABLE_FIELDS:
            if field in values and field not in REQUIRED_FIELDS:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["产品状态"] = entry["status"]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["状态变更记录"] = []
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据产品定义可执行范围"
        with store.lock(MODULE):
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"数据产品 {entry_id} 不存在或已归档"
            allowed_statuses, target = ACTION_RULES[action]
            current = str(entry.get("status", ""))
            if current not in allowed_statuses:
                return (
                    None,
                    f"产品当前为「{current}」状态，不允许执行{action}；允许的前置状态为"
                    f"{'、'.join(allowed_statuses)}",
                )
            if target not in STATUS_ORDER:
                return None, f"目标状态「{target}」不在允许的状态序列里"
            entry["status"] = target
            entry["产品状态"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
            entry.setdefault("状态变更记录", []).append({
                "动作": action,
                "from": current,
                "to": target,
                "时间": date.today().isoformat(),
            })
            return entry, f"数据产品已{action}"
