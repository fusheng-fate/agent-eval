# Datasets 页面（数据集管理）

## 职责
数据集管理（v3.0 第 4.1 步）：上传 Excel + 动态列映射 + 前 5 行预览 + 筛选 + 删除（owner-or-admin）。从旧"导入/生成/审查/快照"4 页合并为单页。

## 路由
`/datasets`

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `datasets.list` | GET `/datasets` | 列表（owner=mine/all，keyword） |
| `datasets.get` | GET `/datasets/{id}` | 详情 |
| `datasets.preview` | GET `/datasets/{id}/preview` | 预览（表头 + 前 5 行） |
| `datasets.cases` | GET `/datasets/{id}/cases` | 用例分页 |
| `datasets.upload` | POST `/datasets/upload` | Excel 上传（FormData：file + name + column_mapping） |
| `datasets.delete` | DELETE `/datasets/{id}` | 删除（owner-or-admin） |

## 布局
- **数据集列表**：表格（名称/用例数/创建人/创建时间/操作），筛选（我的/全部 + 搜索）
- **上传区**：
  1. 选文件（.xlsx）
  2. 填名称
  3. **列映射**：读 Excel 表头 → 下拉选择映射到 case_no/user_input/expected_gt（必填）+ dimension_l1/dimension_l2（可选）
  4. 预览前 5 行（映射后）
  5. 上传
- **数据集详情**（点击行）：预览（表头+前5行）+ 用例分页 + 删除

## 关键交互
- **列映射**（P24）：上传时前端读 Excel 第一行表头，渲染下拉框让用户选"哪个表头 → 哪个字段"。必填列未映射时上传按钮禁用。
- 预览：映射后显示前 5 行数据，核验准确性。
- 删除：二次确认（普通用户仅自己的可删，按钮按 owner 显隐）。

## 权限
- 列表/预览/用例：所有登录用户（可见全部数据集）
- 上传：所有登录用户
- 删除：owner-or-admin（普通用户仅自己的，admin 全部）

## TODO
- [ ] 上传前文件校验（大小/格式）
- [ ] 大文件分片上传
- [ ] 数据集版本历史
- [ ] 用例编辑（当前只读）

## 协作守则
- column_mapping 是 JSON 字符串，前端序列化后传 FormData。
- 列映射的表头读取用 SheetJS（xlsx 库）或后端返回（当前前端需自己读）。
- 删除是级联（cases 一起删），确认弹窗要提示。
