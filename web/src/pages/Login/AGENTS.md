# Login 页面

## 职责
登录页（v3.0 第 0 步）：账号密码 → 登录 → 存 token → 跳任务中心。

## 路由
`/login`

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `auth.login` | POST `/auth/login` | 登录，返回 token + user |

## 逻辑
1. 表单：username + password
2. 提交 → `auth.login` → 成功：`setToken(token)` + 存 user 到 AuthContext → 跳 `/`（或登录前路径）
3. 失败：显示错误（401 用户名或密码错误 / 403 账号已停用）
4. 已登录访问 /login → 直接跳 `/`

## 组件
- 登录卡片（白底 16px 圆角，居中）
- 用户名/密码输入框（聚焦边框转 `#C7000B`）
- 登录按钮（主按钮 `#C7000B`）
- 错误提示（`#F56C6C`）

## 权限
- 公开页（不需 token）

## TODO
- [ ] 记住用户名（localStorage）
- [ ] 登录失败次数提示（后端限流后）
- [ ] 登录态过期回跳当前路径

## 协作守则
- token 存 localStorage（`http.ts` 的 `setToken` 统一管理）。
- 登录成功后必须初始化 AuthContext（调 `/auth/me` 或直接用 login 返回的 user）。
