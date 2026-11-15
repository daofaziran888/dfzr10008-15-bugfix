#!/usr/bin/env python3
"""市场分发链路 HTTP 级验证（仅用标准库 urllib，对着运行中的 uvicorn 打）。"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
failures: list[str] = []


def call(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    # 查询串里的中文需要百分号编码，结构字符保留。
    if "?" in path:
        base_path, query = path.split("?", 1)
        path = base_path + "?" + urllib.parse.quote(query, safe="=&")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        # HTTP 头只接受 latin-1，中文身份值用 RFC 2047 风格的百分号编码传递，服务端解码。
        if isinstance(v, str):
            v = urllib.parse.quote(v)
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    status, health = call("GET", "/api/health")
    check("服务健康", status == 200 and health["ok"] is True, str(health))

    # 列表页：种子数据可读且状态一致
    status, page = call("GET", "/api/market?status=草稿")
    check("列表接口 200", status == 200)
    mkt2 = next((r for r in page["items"] if r["商品编号"] == "MKT-0002"), None)
    check("列表页 MKT-0002 定价方案完整", mkt2 and mkt2["定价方案"] == "99 元/月", str(mkt2))
    check("列表页 MKT-0002 试用天数完整", mkt2 and mkt2["试用天数"] == 14)
    check("列表页 MKT-0002 上线时间完整", mkt2 and mkt2["上线时间"] == "2026-12-01")
    check("列表页 MKT-0002 商品归属完整", mkt2 and mkt2["商品归属"] == "华东渠道组")
    check("列表页状态无残留", all(r["status"] == r["商品状态"] for r in page["items"]))

    # 详情页：完整字段回显
    status, detail = call("GET", "/api/market/2")
    check("详情接口 200", status == 200)
    check("详情页所属产品 PROD-0002", detail["所属产品"] == "PROD-0002")
    check("详情页定价方案回显", detail["定价方案"] == "99 元/月")
    check("详情页试用配置字段回显", detail["试用天数"] == 14 and detail["上线时间"] == "2026-12-01")

    # PROD-0002 已下线，上架拒绝
    status, res = call("POST", "/api/market/2/actions", {"values": {"action": "上架商品"}})
    check("下线产品上架返回 ok=false", status == 200 and res["ok"] is False and res["code"] == "PRODUCT_OFFLINE", str(res))
    check("拒绝消息可读", "已下线" in res["message"] or "未恢复可分发" in res["message"])

    # 跨单位（华北渠道组）动作被拒
    status, res = call(
        "POST", "/api/market/2/actions",
        {"values": {"action": "上架商品"}},
        {"X-Operator": "华北运营", "X-Operator-Unit": "华北渠道组"},
    )
    check("跨单位操作被拒绝", res["ok"] is False and res["code"] == "CROSS_UNIT", str(res))
    check("跨单位只读详情仍可用", call("GET", "/api/market/2")[0] == 200)

    # 非负责人改共享试用配置被拒
    status, res = call(
        "PUT", "/api/market/2",
        {"values": {"定价方案": "1 元/月"}},
        {"X-Operator": "渠道运营小王", "X-Operator-Unit": "华东渠道组"},
    )
    check("非负责人改试用配置被拒", res["ok"] is False and res["code"] == "FORBIDDEN", str(res))

    # 产品恢复可分发后上架成功，返回完整快照
    status, pres = call("POST", "/api/product/2/actions", {"values": {"action": "发布产品"}})
    check("产品重新发布成功", pres["ok"] is True and pres["entry"]["status"] == "已发布", str(pres))
    status, res = call("POST", "/api/market/2/actions", {"values": {"action": "上架商品"}})
    check("恢复后上架成功", res["ok"] is True and res["entry"]["status"] == "已上架", str(res))
    snap = res["entry"].get("试用配置快照") or {}
    check("上架结果带完整试用配置快照", snap.get("定价方案") == "99 元/月" and snap.get("试用天数") == 14
          and snap.get("上线时间") == "2026-12-01" and snap.get("所属产品") == "PROD-0002", str(snap))

    # 顺序流转：跳过下架直接删除被拒
    status, res = call("POST", "/api/market/2/actions", {"values": {"action": "删除商品"}})
    check("未下架不能删除", res["ok"] is False and res["code"] == "INVALID_STATE")
    status, res = call("POST", "/api/market/2/actions", {"values": {"action": "下架商品"}})
    check("下架成功", res["ok"] is True and res["entry"]["status"] == "已下架")
    check("下架后快照不丢", (res["entry"].get("试用配置快照") or {}).get("试用天数") == 14)
    status, res = call("POST", "/api/market/2/actions", {"values": {"action": "删除商品"}})
    check("下架后可删除", res["ok"] is True and res["entry"]["status"] == "已删除")

    # 编辑接口字段保存回显
    status, res = call("POST", "/api/market", {"values": {
        "商品编号": "MKT-0088", "商品名称": "HTTP 验证商品", "所属产品": "PROD-0001",
        "定价方案": "12 元/月", "试用天数": 9, "上线时间": "2027-03-01", "封面描述": "端到端",
    }})
    check("登记接口全字段保存", res["ok"] is True, str(res))
    new_id = res["entry"]["id"]
    check("登记响应含完整字段", res["entry"]["定价方案"] == "12 元/月" and res["entry"]["试用天数"] == 9)
    status, got = call("GET", f"/api/market/{new_id}")
    check("登记后详情完整回显", got["上线时间"] == "2027-03-01" and got["商品归属"] == "华东渠道组")
    status, res = call("PUT", f"/api/market/{new_id}", {"values": {"封面描述": "端到端-改"}})
    check("编辑接口可保存", res["ok"] is True and res["entry"]["封面描述"] == "端到端-改")

    # 非法动作与不存在资源
    status, res = call("POST", "/api/market/999/actions", {"values": {"action": "下架商品"}})
    check("不存在商品返回 NOT_FOUND", res["ok"] is False and res["code"] == "NOT_FOUND")
    status, res = call("POST", f"/api/market/{new_id}/actions", {"values": {"action": "飞天"}})
    check("非法动作被拒", res["ok"] is False and res["code"] == "INVALID_ACTION")

    print()
    if failures:
        print(f"共 {len(failures)} 项失败：{failures}")
        return 1
    print("全部 HTTP 级验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
