"""操作人身份与跨单位权限。

市场商品按「商品归属」划给渠道组（单位）维护。写操作必须带操作人信息：
优先读请求头（X-Operator / X-Operator-Unit），其次读请求体 values 里的同名字段；
都没带时回落到演示用默认身份，保证页面本地演示仍可走通，但显式声明的跨单位
操作会被严格拒绝。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import Request

# 演示环境默认身份：与种子数据里的商品归属保持同一个渠道组。
DEFAULT_OPERATOR = "值班管理员"
DEFAULT_UNIT = "华东渠道组"

OPERATOR_HEADER = "X-Operator"
UNIT_HEADER = "X-Operator-Unit"


@dataclass(frozen=True)
class Operator:
    name: str
    unit: str

    @property
    def identity(self) -> str:
        return f"{self.name}（{self.unit}）"


def resolve_operator(request: Request, values: dict[str, Any] | None = None) -> Operator:
    """从请求头或请求体解析操作人；字段缺失时回落默认演示身份。

    HTTP 头只接受 latin-1，调用方传中文身份时按百分号编码，这里统一解码。
    """
    values = values or {}
    name = _clean(_header(request, OPERATOR_HEADER)) or _clean(values.get("operator")) or DEFAULT_OPERATOR
    unit = _clean(_header(request, UNIT_HEADER)) or _clean(values.get("operatorUnit")) or DEFAULT_UNIT
    return Operator(name=name, unit=unit)


def _header(request: Request, key: str) -> str:
    raw = request.headers.get(key)
    return unquote(raw).strip() if raw else ""


def ensure_same_unit(operator: Operator, owner_unit: str, *, resource: str = "市场商品") -> str | None:
    """跨单位写操作一律拒绝；返回可读错误，None 表示放行。"""
    if _clean(owner_unit) and operator.unit != owner_unit:
        return f"跨单位操作被拒绝：{resource}归属「{owner_unit}」，{operator.identity}只有只读权限"
    return None


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""
