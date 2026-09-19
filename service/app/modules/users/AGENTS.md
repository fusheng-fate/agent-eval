# users 模块

## 职责
用户管理（仅管理员）：列表、注册、改密、停用。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/users` | admin | 用户列表，`?keyword=&page=&page_size=` 分页（默认 20，上限 100），keyword 匹配 username/display_name |
| POST | `/api/users` | admin | 注册普通用户（role 固定 tester）`{username, password, display_name}` |
| PUT | `/api/users/{id}/password` | admin | 改指定用户密码 `{password}` |
| DELETE | `/api/users/{id}` | admin | 停用用户（软删除，is_active=False） |

## 文件
- `routes.py` — 路由（4 接口）
- `schemas.py` — UserOut / CreateUserReq / ChangePasswordReq / UserListOut

## 响应（统一包裹结构）
所有接口统一返回 `{code, message, data}`（见 `docs/服务化数据模型与接口.md` 的 API 响应规范）。

- 成功：`code=0, message="ok"`；`data` 为接口实际内容。
- 业务失败：HTTP 200 + 非 0 `code`（如用户名已存在 `40902`），`data=null`。
- 真正异常（未认证/无权限/资源不存在）仍用 4xx。
- `GET /users` 的 `data` 为分页结构 `{items, page, page_size, total}`。
- 创建用户成功返回 HTTP 201；列表/改密/停用成功返回 HTTP 200。

通用辅助：`app.modules.shared` 提供 `ok(data=None)` / `fail(code, message)` 生成包裹结构。

## 依赖
- `app.core.deps` — `require_admin`
- `app.core.security` — `hash_password`
- `app.models.User`

## 数据模型
- `User`（`app/models/user.py`）

## 权限
- 全部接口仅 admin（`require_admin`）
- 不能停用自己
- 不能停用初始管理员（username == admin 且 role == admin）
- 管理员注册的用户 role 固定为 `tester`（普通用户）

## TODO
- [ ] 用户角色变更接口（当前只能注册 tester，不能提升为 admin）
- [ ] 停用后已有任务的清理策略

## 协作守则
- `UserOut` 与 auth 模块各有一份，字段变更需同步。
- 停用是软删除（is_active=False），不物理删除，保留历史任务关联。

## 单元测试
- 开发完成后自动在当前模块创建__test目录，对当前模块的所有接口进行单元测试
- 输出测试用例总数、通过个数、未通过个数、未通过原因
