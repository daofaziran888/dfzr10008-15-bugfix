# 数据产品与API工厂

面向数据产品经理与开发者的数据产品快速构建平台。覆盖数据产品定义、API接口生成、数据模型封装、产品版本管理、调用配额控制、文档自动生成、产品市场分发与使用效果追踪的完整数据产品链路。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据产品定义 | `product` | 数据产品 | 产品编号、产品名称、产品类型 |
| API接口生成 | `apigen` | 接口配置 | 接口编号、接口名称、请求方法 |
| 数据模型封装 | `datapack` | 模型封装 | 封装编号、封装名称、原始数据源 |
| 产品版本管理 | `version` | 产品版本 | 版本编号、产品名称、版本号 |
| 调用配额控制 | `quota` | 配额配置 | 配置编号、调用方名称、每秒上限 |
| 文档自动生成 | `docgen` | 文档模板 | 模板编号、文档标题、目标接口 |
| 产品市场分发 | `market` | 市场商品 | 商品编号、商品名称、所属产品 |
| 使用效果追踪 | `usage` | 使用记录 | 记录编号、产品名称、调用方名称 |
| 产品沙箱测试 | `sandbox` | 沙箱实例 | 实例编号、测试产品、测试参数 |
| 数据管线编排 | `pipeline` | 管线节点 | 节点编号、节点名称、上游节点 |
| 数据筛选引擎 | `filter` | 筛选模板 | 模板编号、模板名称、目标数据源 |
| 场景化配置模板 | `scene` | 场景模板 | 模板编号、模板名称、适用场景 |
| 实时数据推送 | `realtime` | 推送通道 | 通道编号、通道名称、数据源名称 |
| 跨源数据关联 | `crossref` | 关联规则 | 规则编号、主数据源、关联数据源 |
| 数据质量反馈 | `feedback` | 反馈记录 | 反馈编号、数据产品、反馈类型 |
| 数据产品认证 | `badge` | 认证记录 | 认证编号、产品名称、认证类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message, code, entry }`，
  其中 `code` 为机器可读的拒绝原因（如 `PRODUCT_OFFLINE`、`CROSS_UNIT`、`INVALID_STATE`）。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断；写操作在模块锁
  （`app/store.py` 的 `store.lock(module)`）内完成「读状态→校验→落状态」。

### 产品市场分发（market）业务约束

- **全字段登记**：定价方案、试用天数、上线时间、封面描述、商品归属随登记/编辑完整落库回显；
  商品编号与商品归属为不可变字段。
- **上架前置校验**：只有「草稿」商品且所属产品处于「已发布」可分发状态才能上架；
  产品「已下线」时上架返回 `PRODUCT_OFFLINE`，产品重新发布恢复可分发后才可上架。
- **状态顺序**：草稿 → 已上架 → 已下架 → 已删除，只能逐步推进，跳转动作被
  `INVALID_STATE` 拒绝；`status` 与「商品状态」字段始终同步，列表页无状态残留。
- **试用配置快照**：上架成功时固化完整试用配置（定价方案、试用天数、上线时间、
  所属产品、商品归属等）到 `试用配置快照`，后续下架/删除不覆盖、不丢失。
- **单位权限**：写操作按「商品归属」做单位级控制，跨单位只读，越权写返回
  `CROSS_UNIT`；共享试用配置（定价方案、试用天数、上线时间）仅商品登记人可改，
  同单位其他运营修改返回 `FORBIDDEN`。
- **并发安全**：同一商品并发下架时，模块锁保证只有第一个请求落一次状态变化，
  其余请求看到的已是「已下架」而被状态机拒绝。
- 操作人身份通过请求头 `X-Operator` / `X-Operator-Unit` 传递（中文值百分号编码），
  也可放在请求体 `values.operator` / `values.operatorUnit`；缺失时回落默认演示身份。
- 前端页头可切换操作单位，切到非归属渠道组后市场页自动进入只读态。

### 验证脚本（仅依赖标准库，无需 pytest）

```bash
cd backend
.venv/bin/python tests/verify_service.py   # 服务级：含 8 线程并发下架验证
.venv/bin/uvicorn app.main:app --port 8000 # 另开一个终端起服务
.venv/bin/python tests/verify_http.py      # HTTP 级：对运行中的服务打全链路用例
```

领域：数据工程
子方向：数据分析与数据应用
