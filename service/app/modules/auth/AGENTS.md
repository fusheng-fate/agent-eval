# auth 模块

## 职责
认证：登录、刷新令牌、登出、获取当前用户、改自己密码。所有其他模块的鉴权入口。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/login` | 公开 | 账号密码登录，返回 access + refresh 双 JWT + UserOut |
| POST | `/api/auth/refresh` | 公开（凭 refresh token） | 用 refresh token 换新双 JWT，refresh 同步轮换 |
| POST | `/api/auth/logout` | 登录用户 | 登出，access token 的 `jti` 加入 Redis 黑名单（幂等） |
| GET | `/api/auth/me` | 登录用户 | 返回当前用户 |
| PUT | `/api/auth/me/password` | 登录用户 | 改自己密码 |

## 文件
- `routes.py` — 路由（5 接口）
- `schemas.py` — LoginReq / TokenResp / RefreshReq / RefreshResp / UserOut / ChangePasswordReq

## 依赖
- `app.core.security` — `verify_password` / `hash_password` / `create_access_token` / `create_refresh_token` / `decode_access_token` / `decode_refresh_token` / `blacklist_jti`
- `app.core.deps` — `get_current_user` / `bearer`（其他模块用 `get_current_user`，本模块 login / refresh / logout 不依赖它）
- `app.models.User`

## 响应（统一包裹结构）
所有接口统一返回 `{code, message, data}`（见 `docs/服务化数据模型与接口.md` 的 API 响应规范）。

- 成功：`code=0, message="ok"`；`data` 为接口实际内容。
- 登录/刷新 `data`：`{access_token, refresh_token, token_type, expires_in, user(仅 login)}`；`expires_in` 为 access token 剩余秒数。
- 真正异常（未认证/密码错误/令牌无效/账号停用）仍用 4xx（401/403）。
- 通用辅助：`app.modules.shared` 的 `ok(data=None)` / `fail(code, message)`。

## 令牌机制
- 双 token：`access`（12h）承载鉴权；`refresh`（7d）仅用于 `/auth/refresh` 换新。
- token payload 含 `type` 字段区分 access/refresh，防止混用。
- refresh 每次使用即轮换（旧 refresh 不再返回，客户端需保存新值）。
- 登出吊销：`logout` 把 access token 的 `jti` 写入 Redis 黑名单（TTL=剩余有效期），`get_current_user` 校验时命中即 401；重复登出/无效 token 幂等返回成功。

## 用户管理归属（非本模块）
「管理员添加用户」及用户增删改查不在 auth 模块，归属 **users 模块**（仅 admin）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/users` | 用户列表（admin） |
| POST | `/api/users` | 添加普通用户（role 固定 tester）`{username, password, display_name}` |
| PUT | `/api/users/{id}/password` | 改任意账号密码（admin） |
| DELETE | `/api/users/{id}` | 停用用户（软删除，不可停自己/初始管理员） |

> 用户模块详见 `dev/service/app/modules/users/AGENTS.md`。

## 数据模型
- `User`（`app/models/user.py`）：username / password_hash / display_name / role / is_active / created_at

## 权限
- login / refresh / logout：公开或凭 token（不校验 access 身份）
- me / me/password：需有效 JWT（`get_current_user`）
- 改自己密码不校验旧密码（骨架简化，生产建议加旧密码校验）

## TODO
- [ ] 改自己密码加旧密码校验
- [ ] 登录失败次数限制（防暴力破解）
- [ ] refresh 令牌作废 / 复用检测（旧 refresh 被重放时吊销整链）

## 协作守则
- 改 `security.py` 的 token 结构会影响所有模块，改前同步。
- `UserOut` 是跨模块共享的（users 模块也定义了一份），保持字段一致。
