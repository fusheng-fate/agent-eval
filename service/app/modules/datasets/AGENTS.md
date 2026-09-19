# datasets 模块

## 职责
数据集管理（P10/P24）：列表、详情、预览（前 5 行）、用例分页、Excel 上传（动态列映射）、删除（owner-or-admin）。

## 接口
| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/datasets` | 登录用户 | 列表（可按 owner/keyword 筛选，owner=mine 只看自己） |
| GET | `/api/datasets/{id}` | 登录用户 | 详情 |
| GET | `/api/datasets/{id}/preview` | 登录用户 | 预览（表头 + 前 5 行） |
| GET | `/api/datasets/{id}/cases` | 登录用户 | 用例分页（page/size） |
| POST | `/api/datasets/upload` | 登录用户 | Excel 上传（multipart：file + name + column_mapping JSON） |
| DELETE | `/api/datasets/{id}` | owner-or-admin | 删除（普通用户仅自己的，管理员全部） |

## 文件
- `routes.py` — 路由（6 接口）
- `schemas.py` — DatasetOut / CaseOut / DatasetPreviewOut / ColumnMapping / DatasetListOut / CaseListOut

## 响应（统一包裹结构）
所有接口统一返回 `{code, message, data}`（见 `docs/服务化数据模型与接口.md` 的 API 响应规范）。

- 成功：`code=0, message="ok"`；`data` 为接口实际内容。
- 列表 `GET /datasets` 与 `GET /datasets/{id}/cases` 的 `data` 为分页结构 `{items, page, page_size, total}`。
- 异常（未认证/无权限/不存在/参数错）用 4xx，由全局中间件 `WrapErrorMiddleware` 包裹为 `{code, message, data}`。
- 上传成功返回 HTTP 201。
- 通用辅助：`app.modules.shared` 的 `ok(data=None)`。

## 依赖
- `app.core.deps` — `get_current_user` / `require_owner_or_admin`
- `app.models.Dataset` / `app.models.Case`
- `openpyxl` — Excel 解析

## 数据模型
- `Dataset`（`app/models/dataset.py`）：name / owner_id / source / case_count / column_mapping / created_at
- `Case`（`app/models/dataset.py`）：dataset_id / case_no / user_input / expected_gt / dimension_l1 / dimension_l2 / preset / steps / tags / extra / sort_order

## 权限
- 读：所有登录用户可见全部数据集
- 删：owner-or-admin（`require_owner_or_admin`）——普通用户仅自己的，管理员全部

## 关键概念
- **动态列映射**（P24）：上传时前端传 `column_mapping`（JSON），指定 Excel 表头 → 字段的映射。
  - 必填列：`case_no`（用例编号）/ `user_input`（测试输入）/ `expected_gt`（预期结果）
  - 可选列：`dimension_l1`（评测一级维度）/ `dimension_l2`（评测二级维度）——用于报告维度汇总
- 缺必填列的行跳过（不报错）
- 仅支持 `.xlsx`
- `column_mapping` 存入 Dataset，预览/导出时复用

## TODO
- [ ] 上传前文件校验（大小限制、格式校验）
- [ ] 大文件分片上传（当前一次性读入内存）
- [ ] 数据集版本管理（同一数据集多次上传的历史）
- [ ] 数据集共享/权限细化（当前仅 owner-or-admin）

## 协作守则
- `column_mapping` 是 JSON 字符串（Form 字段），前端序列化后传，后端 `json.loads` 解析。
- 删除数据集会级联删除 cases（外键），确认前端有二次确认。
