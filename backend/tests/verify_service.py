#!/usr/bin/env python3
"""市场分发链路服务级验证（仅用标准库）。

覆盖：登记字段完整回显、下线产品拒绝上架、恢复可分发后上架、试用配置快照、
状态顺序流转、跨单位只读、非负责人禁改共享试用配置、并发下架只落一次。
"""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import Operator
from app.services.market import MODULE as MARKET_MODULE
from app.services.market import MarketService
from app.services.product import ProductService
from app.store import store

HUADONG = Operator("值班管理员", "华东渠道组")
HUADONG_OTHER = Operator("渠道运营小王", "华东渠道组")
HUABEI = Operator("渠道运营小李", "华北渠道组")

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def reset() -> None:
    store.__init__()


def main() -> int:
    svc = MarketService()
    psvc = ProductService()

    # ---- A. MKT-0002 登记值完整回显 ----
    reset()
    entry = svc.get_entry(2)
    check("MKT-0002 所属产品为 PROD-0002", entry["所属产品"] == "PROD-0002", str(entry.get("所属产品")))
    check("MKT-0002 定价方案回显 99 元/月", entry["定价方案"] == "99 元/月", str(entry.get("定价方案")))
    check("MKT-0002 试用天数回显 14", entry["试用天数"] == 14, str(entry.get("试用天数")))
    check("MKT-0002 上线时间回显 2026-12-01", entry["上线时间"] == "2026-12-01", str(entry.get("上线时间")))
    check("MKT-0002 商品归属回显 华东渠道组", entry["商品归属"] == "华东渠道组", str(entry.get("商品归属")))
    check("MKT-0002 初始为草稿", entry["status"] == "草稿" and entry["商品状态"] == "草稿")

    # 新登记一条全字段商品，确认不再静默丢字段
    created, msg, code = svc.create_entry({
        "商品编号": "MKT-0009",
        "商品名称": "验证用商品",
        "所属产品": "PROD-0001",
        "定价方案": "59 元/季",
        "试用天数": "5",
        "封面描述": "全字段保存验证",
        "上线时间": "2027-01-01",
    }, HUADONG)
    check("全字段登记成功", code is None and created is not None, msg)
    again = svc.get_entry(created["id"])
    check("登记后定价方案已落库", again["定价方案"] == "59 元/季")
    check("登记后试用天数已落库并转整数", again["试用天数"] == 5)
    check("登记后上线时间已落库", again["上线时间"] == "2027-01-01")
    check("登记后商品归属默认取操作人单位", again["商品归属"] == "华东渠道组")
    check("草稿阶段无试用配置快照", again["试用配置快照"] is None)

    # ---- B. 产品已下线，上架必须被拒绝 ----
    reset()
    before = svc.get_entry(2)["status"]
    entry, msg, code = svc.run_action(2, "上架商品", HUADONG)
    check("PROD-0002 已下线时上架被拒绝", entry is None and code == "PRODUCT_OFFLINE", msg)
    check("拒绝上架后商品仍为草稿（状态无残留）", svc.get_entry(2)["status"] == before == "草稿")
    check("拒绝上架未产生快照", svc.get_entry(2)["试用配置快照"] is None)

    # ---- C. 产品恢复可分发后草稿才能上架，上架带完整快照 ----
    product, pmsg = psvc.run_action(2, "发布产品")
    check("PROD-0002 重新发布恢复可分发", product is not None and product["status"] == "已发布", pmsg)
    entry, msg, code = svc.run_action(2, "上架商品", HUADONG)
    check("恢复可分发后上架成功", code is None and entry["status"] == "已上架", msg)
    check("上架后商品状态同步为已上架", entry["商品状态"] == "已上架")
    snap = entry["试用配置快照"]
    check("上架结果带完整试用配置快照", isinstance(snap, dict), str(type(snap)))
    if snap:
        check("快照含定价方案 99 元/月", snap["定价方案"] == "99 元/月")
        check("快照含试用天数 14", snap["试用天数"] == 14)
        check("快照含上线时间 2026-12-01", snap["上线时间"] == "2026-12-01")
        check("快照含所属产品 PROD-0002", snap["所属产品"] == "PROD-0002")
        check("快照含商品归属 华东渠道组", snap["商品归属"] == "华东渠道组")

    # ---- D. 状态必须按顺序流转，下架/删除后快照不丢 ----
    entry, msg, code = svc.run_action(2, "上架商品", HUADONG)
    check("已上架商品不能再次上架", code == "INVALID_STATE", msg)
    entry, msg, code = svc.run_action(2, "删除商品", HUADONG)
    check("已上架商品不能直接删除", code == "INVALID_STATE", msg)
    entry, msg, code = svc.run_action(2, "下架商品", HUADONG)
    check("已上架商品可下架", code is None and entry["status"] == "已下架", msg)
    check("下架后试用配置快照未丢失", entry["试用配置快照"] is not None
          and entry["试用配置快照"]["定价方案"] == "99 元/月")
    entry, msg, code = svc.run_action(2, "下架商品", HUADONG)
    check("已下架商品不能重复下架", code == "INVALID_STATE", msg)
    entry, msg, code = svc.run_action(2, "删除商品", HUADONG)
    check("已下架商品可删除", code is None and entry["status"] == "已删除", msg)
    check("删除后快照仍保留", entry["试用配置快照"] is not None)
    logs = svc.get_entry(2)["状态变更记录"]
    check("状态变更记录完整", [x["动作"] for x in logs] == ["上架商品", "下架商品", "删除商品"], str(logs))

    # ---- E. 权限：跨单位只读、非负责人禁改共享试用配置 ----
    reset()
    # 先准备一条已上架商品（PROD-0001 已发布）
    ok_entry, _, _ = svc.create_entry({
        "商品编号": "MKT-0010", "商品名称": "权限验证商品", "所属产品": "PROD-0001",
        "定价方案": "10 元/月", "试用天数": 3, "上线时间": "2026-12-10",
    }, HUADONG)
    svc.run_action(ok_entry["id"], "上架商品", HUADONG)

    # 跨单位写操作被拒绝，读操作放行
    entry, msg, code = svc.run_action(ok_entry["id"], "下架商品", HUABEI)
    check("跨单位下架被拒绝", code == "CROSS_UNIT", msg)
    check("跨单位拒绝后状态不变", svc.get_entry(ok_entry["id"])["status"] == "已上架")
    readable = svc.get_entry(ok_entry["id"])
    check("跨单位仍可只读详情", readable is not None and readable["商品编号"] == "MKT-0010")
    entry, msg, code = svc.update_entry(ok_entry["id"], {"封面描述": "想越权改描述"}, HUABEI)
    check("跨单位编辑被拒绝", code == "CROSS_UNIT", msg)
    entry, msg, code = svc.create_entry({
        "商品编号": "MKT-0011", "商品名称": "跨单位登记", "所属产品": "PROD-0001",
        "商品归属": "华东渠道组",
    }, HUABEI)
    check("跨单位登记被拒绝", code == "CROSS_UNIT", msg)

    # 同单位非负责人：不能改共享试用配置，但能改普通字段
    entry, msg, code = svc.update_entry(ok_entry["id"], {"定价方案": "1 元/月"}, HUADONG_OTHER)
    check("非负责人改定价方案被拒绝", code == "FORBIDDEN", msg)
    entry, msg, code = svc.update_entry(ok_entry["id"], {"试用天数": 99}, HUADONG_OTHER)
    check("非负责人改试用天数被拒绝", code == "FORBIDDEN", msg)
    check("拒绝后试用天数未被写坏", svc.get_entry(ok_entry["id"])["试用天数"] == 3)
    entry, msg, code = svc.update_entry(ok_entry["id"], {"封面描述": "同单位运营更新封面"}, HUADONG_OTHER)
    check("同单位非负责人可改非试用字段", code is None and entry["封面描述"] == "同单位运营更新封面", msg)
    # 登记人本人可改试用配置
    entry, msg, code = svc.update_entry(ok_entry["id"], {"定价方案": "8 元/月"}, HUADONG)
    check("登记人可修改共享试用配置", code is None and entry["定价方案"] == "8 元/月", msg)
    # 不可变字段
    entry, msg, code = svc.update_entry(ok_entry["id"], {"商品编号": "MKT-9999"}, HUADONG)
    check("商品编号不可变", code == "FORBIDDEN", msg)
    entry, msg, code = svc.update_entry(ok_entry["id"], {"商品归属": "华北渠道组"}, HUADONG)
    check("商品归属不可变", code == "FORBIDDEN", msg)

    # ---- F. 并发下架：同一商品只落一次状态变化 ----
    reset()
    target, _, _ = svc.create_entry({
        "商品编号": "MKT-0020", "商品名称": "并发下架验证", "所属产品": "PROD-0001",
        "定价方案": "10 元/月", "试用天数": 3, "上线时间": "2026-12-10",
    }, HUADONG)
    entry, msg, code = svc.run_action(target["id"], "上架商品", HUADONG)
    snapshot_before = dict(entry["试用配置快照"])

    results: list[tuple[str, str | None]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(svc.run_action, target["id"], "下架商品", HUADONG) for _ in range(8)]
        for fut in concurrent.futures.as_completed(futures):
            _e, m, c = fut.result()
            results.append((m, c))
    successes = [r for r in results if r[1] is None]
    rejected = [r for r in results if r[1] == "INVALID_STATE"]
    check("8 个并发下架仅 1 次成功", len(successes) == 1, str(results))
    check("其余 7 次并发下架被状态机拒绝", len(rejected) == 7, str(results))
    final = svc.get_entry(target["id"])
    check("并发后商品状态为已下架", final["status"] == "已下架" and final["商品状态"] == "已下架")
    off_logs = [x for x in final["状态变更记录"] if x["动作"] == "下架商品"]
    check("状态变更记录里下架只落一次", len(off_logs) == 1, str(off_logs))
    check("并发下架后快照完整未丢失", final["试用配置快照"] == snapshot_before)

    # ---- G. 列表页：状态与商品状态一致、过滤生效 ----
    reset()
    items, total = svc.list_entries(status="草稿")
    check("列表按草稿过滤", total == 2 and all(r["status"] == r["商品状态"] == "草稿" for r in items), str(total))
    items, total = svc.list_entries(page=1, size=20)
    check("列表无状态残留", all(r["status"] == r["商品状态"] for r in items))
    check("列表关键字过滤", svc.list_entries(keyword="MKT-0002")[1] == 1)

    print()
    if failures:
        print(f"共 {len(failures)} 项失败：{failures}")
        return 1
    print("全部服务级验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
