# ShopCare Backend

ShopCare 后端把消费者对话转化为可验证、可追踪的电商服务动作。模型用于理解、追问与生成说明；订单、售后、审核、附件和通知服务负责业务事实、权限与状态写入。

面向产品体验与文档入口：[README](../README.md) · [完整 PRD](../docs/ShopCare_PRD.md) · [部署说明](../docs/DEPLOYMENT.md) · [评测说明](eval/README.md)。

## 服务职责

- 账号认证、会话与消费者数据隔离
- 商品目录与模拟平台政策查询
- 本人订单、物流、改址、取消与拦截处理
- 售后申请、凭证、退货单号、时间线与通知
- 人工审核队列、审核结果与消费者端状态同步
- SSE 对话响应、WebSocket 状态推送与离线评测

## API 入口

默认地址：`http://localhost:18001`。

- 健康检查：`GET /health`
- 认证：`/api/v1/login`、`/api/v1/register`、`/api/v1/me`
- 对话与会话：`/api/v1/chat`、`/api/v1/customer/chat-sessions`
- 消费者资源：`/api/v1/customer/orders`、`/refunds`、`/attachments`、`/notifications`
- 审核工作台：`/api/v1/admin/tasks`
- 实时状态：`/api/v1/ws/*`

## 本地运行

在项目根目录配置 `backend/.env` 后：

```bash
docker compose up -d --build
docker compose exec app python scripts/seed_data.py
```

完整配置、演示账号和评测隔离环境见 [部署说明](../docs/DEPLOYMENT.md)。
