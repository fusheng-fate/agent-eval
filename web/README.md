# 前端（改造后落点）

本目录是服务化重构后的**前端独立 Web 应用**落点。

- 现状：占位目录，前端尚未按方案迁移。
- **协作约定**：见 [`AGENTS.md`](./AGENTS.md)（架构 / 请求层 / 路由 / 视觉 / 依赖 / 删除清单）。
- **页面模块**：`src/pages/<Module>/AGENTS.md`，每页职责、消费接口、权限、TODO。
- 改造方案：见 `docs/前端改造方案.md`（去 hostBridge、统一 `apiClient`、按 v3.0 旅程重排页面、视觉对齐 `docs/DESIGN.md`）。
- 旧前端代码（React 18 + Vite 8 + Tailwind 4）作为参考保留在 `reference/legacy/page-src/`。
- 后端：`dev/service/`（FastAPI，33 接口，见 `docs/服务化数据模型与接口.md`）。

## 技术栈（沿用旧版，去桌面宿主）

React 18 + Vite + Tailwind 4 + lucide-react + react-router-dom（+ 可选 @tanstack/react-query）。

## 启动（迁移后）

```bash
cd dev/web
npm install
npm run dev        # 本地开发，VITE_API_BASE 指向 dev/service（默认 /api 或 http://localhost:8000/api）
```
