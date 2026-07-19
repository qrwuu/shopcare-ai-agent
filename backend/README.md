# ShopCare Backend

ShopCare 的后端服务负责把电商对话请求转化为可验证、可追溯的业务动作。它将 Agent 的语言理解能力与订单、售后、审核、通知等确定性服务分层，避免模型直接修改高风险业务数据。

## 服务职责

- 用户认证、会话管理与消费者数据隔离
- 商品目录与平台政策咨询
- 订单、物流、地址、取消与物流拦截服务
- 售后状态机：退货退款、仅退款、换货、少件、错发、破损与凭证补充
- 人工审核队列、审核记录、通知与原对话同步
- SSE 聊天输出与 WebSocket 状态推送
- 版本化 Agent 回归评测与执行 telemetry

## 核心模块

```text
app/
├── api/v1/          # Auth、Chat、Customer、Conversations、Admin、Status、WebSocket
├── services/        # Agent 编排、上下文、订单/售后、目录、政策、权限与 telemetry
├── graph/           # LangGraph 兼容工作流与 RAG 节点
├── models/          # SQLModel 数据模型
├── tasks/           # Celery 异步任务
└── websocket/       # 连接与事件管理
```

## API 入口

服务默认运行在 `http://localhost:18001`：

- 健康检查：`GET /health`
- OpenAPI 文档：`/docs`
- 认证：`/api/v1/login`、`/api/v1/register`、`/api/v1/me`
- 对话：`POST /api/v1/chat`、`/api/v1/customer/chat-sessions`
- 消费者资源：`/api/v1/customer/orders`、`/refunds`、`/attachments`、`/notifications`
- 审核工作台：`/api/v1/admin/tasks`
- 实时订阅：`/api/v1/ws/*`

## 本地开发

完整启动方式、环境变量说明和演示账号请查看仓库根目录 [README](../README.md)。

后端服务启动前需配置 `backend/.env`，再在项目根目录执行：

```bash
docker compose up -d --build
docker compose exec app python scripts/seed_data.py
```

## 质量保障

`eval/` 提供针对真实 HTTP/SSE 链路的隔离回归评测，覆盖商品、政策、订单、物流、售后、权限隔离、提示注入与关键动作确认。详见 [Agent 离线评测说明](eval/README.md)。
