# 前端 · Agent 评测平台（服务化）

独立 Web 应用（去桌面宿主）。本目录是前端落点，当前为占位，按 `docs/前端改造方案.md` 迁移。

## 技术栈
React 18 · Vite · Tailwind 4 · lucide-react · react-router-dom（+ 可选 @tanstack/react-query）

## 目录结构（迁移后）
```
dev/web/
├── AGENTS.md              # 本文件：前端总约定
├── index.html
├── vite.config.ts
├── tailwind.config.ts     # 设计令牌（DESIGN.md 色板）
├── .env                   # VITE_API_BASE=/api
└── src/
    ├── main.tsx
    ├── App.tsx            # 路由 + 全局布局（左栏+TopBar，无右栏）+ 路由守卫
    ├── lib/
    │   ├── http.ts        # 统一请求层 api<T>() + JWT 拦截器 + ApiError
    │   └── api.ts         # 33 接口封装（按后端模块分组导出）
    ├── context/
    │   └── AuthContext.tsx # 当前用户 + 角色（/auth/me）
    ├── components/        # 通用组件（按钮/卡片/输入/表格/徽章，对齐 DESIGN.md）
    └── pages/             # 页面模块（每模块自带 AGENTS.md）
        ├── Login/
        ├── TaskCenter/    # 任务中心（看板 + 任务列表）
        ├── RunDetail/     # 任务详情
        ├── CaseResult/    # 单用例结果
        ├── Evaluator/     # 评估体系（标准评估器 + 指标库）
        ├── Datasets/      # 数据集管理
        ├── Execution/     # 评测执行（页签式）
        ├── Reports/       # 报告中心
        └── Configs/       # 配置中心
```

## 核心约定

### 1. 统一请求层（`lib/http.ts`）
- `api<T>(path, opts)`：配置化 base（`VITE_API_BASE`，默认 `/api`）+ JWT 拦截器（`Authorization: Bearer`）+ 统一错误（`ApiError`）。
- 401 → 清 token → 跳 `/login`（保留当前路径登录后回跳）。
- 文件上传 `apiUpload`（FormData）、下载 `apiDownload`（blob）。
- **禁止**硬编码 `127.0.0.1:xxxx`，**禁止**裸 fetch，**禁止** hostBridge。

### 2. 接口对应（`lib/api.ts`）
- 每个函数对应 `docs/服务化数据模型与接口.md` 的一个接口（33 个），按后端模块分组：auth / users / metrics / evaluators / datasets / flowTemplates / runs / reports / configs / dashboard。
- 与后端 `dev/service/app/modules/` 一一对应。

### 3. 路由（v3.0 旅程）
```
/login              登录
/                   任务中心（默认落点）
/runs/:id           任务详情
/runs/:id/cases/:caseId  单用例结果
/evaluator          评估体系
/datasets           数据集管理
/execution          评测执行（页签式）
/reports            报告中心列表
/reports/:id        报告详情
/configs            配置中心
```
- 路由守卫：未登录 → /login；管理员专属编辑态，普通用户进只读态。
- 全局布局：左栏菜单（6 项）+ TopBar（用户+角色+退出）+ 主区，**无右栏**。

### 4. 状态管理
- 全局：当前用户 + 角色（AuthContext，`/auth/me`）。
- 页面级：各页从后端拉取（React Query 推荐，或 useState + useEffect）。
- 任务进度：轮询 `GET /runs/{id}`（2s）；后续可加 SSE。

### 5. 权限显隐（双保险）
- 所有"编辑/删除/操作"按钮按 `user.role` + `resource.owner` 控制。
- admin：编辑标准评估器、指标增删改、配置中心、流程模板、用户管理、操作所有任务。
- 普通用户：只读评估器/指标/配置；数据集可见全部但仅删自己的；任务仅操作自己的。
- 后端同样校验，前端仅做显隐。

### 6. 视觉基线（`docs/DESIGN.md`）
- 品牌红 `#C7000B`（仅点缀：主按钮/Logo/标题强调/悬停高亮，唯一暖色，克制用）。
- 蓝灰中性色：页面底 `#EBEFF5`、卡片白 `#FFFFFF`（16px 圆角，默认无阴影）、标题 `#24282E`、正文 `#474E57`、辅助 `#828994`、分割线 `#DCE0E6`。
- 唯一阴影（仅 hover）：`0 2px 20px 0 rgba(0,0,0,0.10)`。
- 圆角只 4px（表单）/ 16px（卡片）；行高恒 1.5；图标细线条线性（lucide）。
- 禁暖灰/米色；卡片默认无阴影。

## 删除清单（迁移时）
hostBridge、optimization 组件、RightPanel、裁判相关、失败归因页、修改建议页、黑灰白盒配置页、结果校准页、StartupGuideDialog、StartTaskDialog、旧 api 文件（lib/api.ts / metrics/api.ts / apiChain/api.ts）。

## 依赖变更
- 新增：`react-router-dom`、`@tanstack/react-query`（可选）
- 保留：`lucide-react`、`tailwindcss`

## 页面模块
每个 `pages/<Module>/` 下有独立 `AGENTS.md`，说明该页职责、消费接口、权限、TODO。认领页面先看对应 AGENTS.md。
