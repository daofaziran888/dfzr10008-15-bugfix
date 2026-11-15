"""产品市场分发接口：维护市场商品，覆盖登记、编辑、上架、下架、删除等动作。

业务判断全部下沉到 MarketService，路由层只负责解析操作人身份与统一返回结构。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.security import resolve_operator
from app.services.market import MarketService

router = APIRouter(prefix="/api/market", tags=["产品市场分发"])

service = MarketService()

LIST_FIELDS = ["商品编号", "商品名称", "所属产品", "定价方案", "试用天数", "封面描述", "上线时间", "商品状态"]
STATUSES = ["草稿", "已上架", "已下架", "已删除"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按商品编号检索"),
    status: str | None = Query(default=None, description="草稿、已上架、已下架、已删除"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按商品编号与状态过滤产品市场分发列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出产品市场分发清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "market", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条市场商品明细（含完整试用配置快照）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"市场商品 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(request: Request, payload: EntryPayload) -> ActionResult:
    """登记一条市场商品，全量字段落库；缺字段或跨单位登记时说明原因而不是静默丢弃。"""
    operator = resolve_operator(request, payload.values)
    entry, message, code = service.create_entry(payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message, code=code)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, request: Request, payload: EntryPayload) -> ActionResult:
    """编辑市场商品：跨单位只读；共享试用配置仅登记人可改，商品编号与归属不可变。"""
    operator = resolve_operator(request, payload.values)
    entry, message, code = service.update_entry(entry_id, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message, code=code)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, request: Request, payload: EntryPayload) -> ActionResult:
    """对单条市场商品执行上架、下架、删除；状态顺序、产品可分发状态与单位权限都在服务层校验。"""
    operator = resolve_operator(request, payload.values)
    action = str(payload.values.get("action") or "").strip()
    entry, message, code = service.run_action(entry_id, action, operator)
    if entry is None:
        return ActionResult(ok=False, message=message, code=code)
    return ActionResult(ok=True, message=message, entry=entry)
