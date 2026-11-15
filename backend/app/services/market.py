"""产品市场分发业务规则：状态流转、字段校验、归属权限与试用配置快照都收在这里。

链路约束（商品登记 → 产品状态 → 市场分发）：
- 登记时保存全量字段，定价方案、试用天数、上线时间、商品归属不再静默丢失；
- 上架前校验所属产品处于「已发布」可分发状态，产品已下线一律拒绝上架；
- 写操作按「商品归属」做单位级权限控制，跨单位只读，共享试用配置仅登记人可改；
- 上架成功时落完整试用配置快照，后续下架/删除都不会覆盖或丢失；
- 状态只能按 草稿→已上架→已下架→已删除 顺序推进，动作在模块锁内执行，
  同一商品并发下架只有第一个请求能落一次状态变化。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.security import Operator, ensure_same_unit
from app.store import store

MODULE = "market"
PRODUCT_MODULE = "product"
REQUIRED_FIELDS = ["商品编号", "商品名称", "所属产品"]
# 登记/编辑允许落库的业务字段白名单，避免把 action、operator 之类的入参写进记录。
EDITABLE_FIELDS = ["商品名称", "所属产品", "定价方案", "试用天数", "封面描述", "上线时间"]
# 共享试用配置：只有商品登记人本人能改，同单位其他运营不可改动。
TRIAL_CONFIG_FIELDS = ["定价方案", "试用天数", "上线时间"]
IMMUTABLE_FIELDS = ["商品编号", "商品归属"]
STATUS_ORDER = ["草稿", "已上架", "已下架", "已删除"]
# 动作 → (前置状态, 目标状态)：前置状态不匹配即拒绝，保证按顺序流转。
ACTION_RULES: dict[str, tuple[str, str]] = {
    "上架商品": ("草稿", "已上架"),
    "下架商品": ("已上架", "已下架"),
    "删除商品": ("已下架", "已删除"),
}
# 产品侧允许市场分发的状态。
DISTRIBUTABLE_PRODUCT_STATUS = "已发布"


class MarketService:
    # ---------- 查询 ----------
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
            rows = [row for row in rows if keyword in str(row.get("商品编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记 ----------
    def create_entry(
        self, values: dict[str, Any], operator: Operator
    ) -> tuple[dict[str, Any] | None, str, str | None]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", "VALIDATION"

        owner_unit = str(values.get("商品归属") or "").strip() or operator.unit
        # 商品归属必须与操作人所在单位一致：不允许替别的渠道组登记商品。
        if owner_unit != operator.unit:
            return (
                None,
                f"跨单位操作被拒绝：商品归属「{owner_unit}」与{operator.identity}所在单位不一致",
                "CROSS_UNIT",
            )

        product_code = str(values["所属产品"]).strip()
        product = self._find_product(product_code)
        if product is None:
            return None, f"所属产品 {product_code} 不存在，无法登记市场商品", "PRODUCT_NOT_FOUND"

        days_error = self._validate_trial_days(values.get("试用天数"))
        if days_error:
            return None, days_error, "VALIDATION"

        rows = store.rows(MODULE)
        duplicate = next((row for row in rows if str(row.get("商品编号")) == str(values["商品编号"]).strip()), None)
        if duplicate is not None:
            return None, f"商品编号 {values['商品编号']} 已存在，不能重复登记", "VALIDATION"

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["商品编号"] = str(values["商品编号"]).strip()
        for field in EDITABLE_FIELDS:
            entry[field] = self._normalize(field, values.get(field))
        entry["所属产品"] = product_code
        entry["商品归属"] = owner_unit
        entry["登记人"] = operator.name
        entry["status"] = STATUS_ORDER[0]
        entry["商品状态"] = entry["status"]
        entry["pending"] = True
        entry["abnormal"] = False
        # 上架时才生成快照，草稿阶段明确为空，避免前端把空壳当成有效试用配置。
        entry["试用配置快照"] = None
        entry["状态变更记录"] = []
        rows.append(entry)
        return entry, "市场商品已登记", None

    # ---------- 编辑 ----------
    def update_entry(
        self, entry_id: int, values: dict[str, Any], operator: Operator
    ) -> tuple[dict[str, Any] | None, str, str | None]:
        with store.lock(MODULE):
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"市场商品 {entry_id} 不存在或已归档", "NOT_FOUND"

            cross_unit = ensure_same_unit(operator, str(entry.get("商品归属", "")))
            if cross_unit:
                return None, cross_unit, "CROSS_UNIT"

            locked = [field for field in IMMUTABLE_FIELDS if field in values and str(values[field] or "").strip()
                      and str(values[field]).strip() != str(entry.get(field, ""))]
            if locked:
                return None, f"{'、'.join(locked)}为不可变字段，不允许修改", "FORBIDDEN"

            # 共享试用配置只有登记人本人能改；同单位其他运营只读这部分。
            trial_changes = [
                field for field in TRIAL_CONFIG_FIELDS
                if field in values and self._normalize(field, values[field]) != entry.get(field)
            ]
            if trial_changes and entry.get("登记人") != operator.name:
                return (
                    None,
                    f"共享试用配置（{'、'.join(trial_changes)}）仅登记人「{entry.get('登记人')}」可修改，"
                    f"{operator.identity}无权改动",
                    "FORBIDDEN",
                )

            days_error = self._validate_trial_days(values.get("试用天数"))
            if days_error:
                return None, days_error, "VALIDATION"

            if "所属产品" in values:
                product_code = str(values["所属产品"]).strip()
                if self._find_product(product_code) is None:
                    return None, f"所属产品 {product_code} 不存在，无法关联", "PRODUCT_NOT_FOUND"

            for field in EDITABLE_FIELDS:
                if field in values:
                    entry[field] = self._normalize(field, values[field])
            return entry, "市场商品已更新", None

    # ---------- 动作流转 ----------
    def run_action(
        self, entry_id: int, action: str, operator: Operator
    ) -> tuple[dict[str, Any] | None, str, str | None]:
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于产品市场分发可执行范围", "INVALID_ACTION"

        # 整段「读状态→校验→落状态」放在模块锁内，并发下架时第二个请求只能看到新状态。
        with store.lock(MODULE):
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"市场商品 {entry_id} 不存在或已归档", "NOT_FOUND"

            cross_unit = ensure_same_unit(operator, str(entry.get("商品归属", "")))
            if cross_unit:
                return None, cross_unit, "CROSS_UNIT"

            required_status, target_status = ACTION_RULES[action]
            current_status = str(entry.get("status", ""))
            if current_status != required_status:
                return (
                    None,
                    f"商品当前为「{current_status}」状态，仅「{required_status}」状态可执行{action}，"
                    f"状态须按 {' → '.join(STATUS_ORDER)} 顺序流转",
                    "INVALID_STATE",
                )

            if action == "上架商品":
                product = self._find_product(str(entry.get("所属产品", "")))
                if product is None:
                    return (
                        None,
                        f"所属产品 {entry.get('所属产品')} 不存在，商品不能上架",
                        "PRODUCT_NOT_FOUND",
                    )
                product_status = str(product.get("status", ""))
                if product_status != DISTRIBUTABLE_PRODUCT_STATUS:
                    return (
                        None,
                        f"所属产品 {product.get('产品编号')} 当前为「{product_status}」状态，未恢复可分发，"
                        f"市场商品不能上架",
                        "PRODUCT_OFFLINE",
                    )
                # 上架即固化完整试用配置快照；之后任何动作都不再覆盖它。
                entry["试用配置快照"] = self._build_trial_snapshot(entry, operator)

            entry["status"] = target_status
            # 商品状态与流程状态始终同步，列表页不再出现状态残留。
            entry["商品状态"] = target_status
            entry["pending"] = target_status != STATUS_ORDER[-1]
            entry["abnormal"] = False
            entry.setdefault("状态变更记录", []).append({
                "动作": action,
                "from": required_status,
                "to": target_status,
                "操作人": operator.name,
                "操作单位": operator.unit,
                "时间": date.today().isoformat(),
            })
            message = f"市场商品已{action}"
            if action == "上架商品":
                message = "市场商品已上架，试用配置快照已固化"
            return entry, message, None

    # ---------- 内部工具 ----------
    def _find_product(self, product_code: str) -> dict[str, Any] | None:
        for row in store.rows(PRODUCT_MODULE):
            if str(row.get("产品编号", "")).strip() == product_code.strip():
                return row
        return None

    def _build_trial_snapshot(self, entry: dict[str, Any], operator: Operator) -> dict[str, Any]:
        """上架时的完整试用配置快照：登记值原样固化，附带快照元数据。"""
        return {
            "商品编号": entry.get("商品编号"),
            "所属产品": entry.get("所属产品"),
            "定价方案": entry.get("定价方案"),
            "试用天数": entry.get("试用天数"),
            "上线时间": entry.get("上线时间"),
            "封面描述": entry.get("封面描述"),
            "商品归属": entry.get("商品归属"),
            "快照时间": date.today().isoformat(),
            "快照操作人": operator.name,
            "快照操作单位": operator.unit,
        }

    def _validate_trial_days(self, value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            days = int(str(value).strip())
        except (TypeError, ValueError):
            return "试用天数必须是非负整数"
        if days < 0:
            return "试用天数不能为负数"
        return None

    def _normalize(self, field: str, value: Any) -> Any:
        if value is None:
            return None
        if field == "试用天数":
            text = str(value).strip()
            return int(text) if text else None
        return str(value).strip()
