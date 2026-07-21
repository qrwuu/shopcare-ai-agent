# 部署与本地体验｜ShopCare

[README](../README.md) · [完整 PRD](ShopCare_PRD.md) · [PRD 精简版](ShopCare_PRD_精简版.md)

## 运行要求

- Docker Engine 与 Docker Compose v2
- Node.js 20+
- 可用的 OpenAI 兼容模型网关

## 配置

```bash
cp backend/.env.example backend/.env
cp web/.env.example web/.env.local
```

在 `backend/.env` 配置：

```dotenv
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=your-api-key
LLM_MODEL=your-chat-model
SECRET_KEY=replace-with-a-long-random-secret
```

`web/.env.local` 默认使用 `BACKEND_URL=http://localhost:18001`。

## 启动服务

```bash
docker compose up -d --build
docker compose exec app python scripts/seed_data.py
```

- Web：`http://localhost:3000`（启动 Web 后）
- API 健康检查：`http://localhost:18001/health`
- API 文档：`http://localhost:18001/docs`

启动 Web：

```bash
cd web
npm ci
npm run dev
```

## 演示账号

| 角色 | 账号 | 密码 | 入口 |
| --- | --- | --- | --- |
| 消费者 | `10000001` | `123456` | `/login` |
| 售后审核员 | `80000001` | `123456` | `/admin/login` |

注册消费者账号后，系统生成独立体验订单。演示订单、物流和售后状态用于完整体验产品流程。

## 隔离评测

```bash
docker compose -f docker-compose.eval.yml up --build -d
cd backend
python -m eval --suite release-v1 --output-dir eval/results
docker compose -f ../docker-compose.eval.yml down
```

评测环境使用独立数据库、Redis 和端口 `18002`，不写入日常演示数据。详见 [Agent 离线评测说明](../backend/eval/README.md)。
