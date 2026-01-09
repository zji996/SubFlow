# SubFlow Web (apps/web)

## 后端地址如何确定

前端代码请求的 API 基址固定为 `'/api'`（见 `apps/web/src/api/client.ts`）。

本地开发时由 Vite Dev Server 代理转发：`apps/web/vite.config.ts` 把 `http://localhost:5173/api/*` 转发到后端 `http://localhost:8100/*`（并去掉 `/api` 前缀）。

## 修改本地开发指向的后端地址

推荐在 `apps/web/.env.local`（已被 gitignore）里配置：

```bash
VITE_API_TARGET=http://localhost:8100
```

也可以临时通过环境变量启动：

```bash
VITE_API_TARGET=http://localhost:8100 npm run dev
```

## 启动

```bash
# 后端
uv run --project apps/api --directory apps/api uvicorn main:app --reload --port 8100

# 前端
cd apps/web
npm run dev
```
