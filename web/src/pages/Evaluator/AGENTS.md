# Evaluator 页面（评估体系）

## 职责
评估体系（v3.0 第 3 步）：标准评估器（管理员可编辑权重/指标，普通只读）+ 指标库（管理员增删改，普通只读）。删裁判 TAB、删新建评估器向导。

## 路由
`/evaluator`

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `evaluators.getStandard` | GET `/evaluators/standard` | 标准评估器（含指标+权重） |
| `evaluators.updateStandard` | PUT `/evaluators/standard` | 更新标准评估器（admin，权重和=1） |
| `metrics.list` | GET `/metrics` | 指标列表（筛选 category/industry/keyword） |
| `metrics.get` | GET `/metrics/{id}` | 指标详情 |
| `metrics.create` | POST `/metrics` | 新建指标（admin） |
| `metrics.update` | PUT `/metrics/{id}` | 更新指标（admin） |
| `metrics.delete` | DELETE `/metrics/{id}` | 删除指标（admin，被引用时 409） |

## 布局（页签式）
- **标准评估器** TAB：
  - 指标权重列表（指标名/权重/阈值，可拖拽排序）
  - 编辑态（admin）：调权重/阈值/增删指标，保存时校验权重和=1
  - 只读态（普通用户）：仅查看
- **指标库** TAB：
  - 指标表格（名称/类别/行业/描述/内置）
  - 筛选（类别/行业/搜索）
  - 编辑态（admin）：新建/编辑/删除指标（含 skill_md 评分要求编辑）
  - 只读态（普通用户）：仅查看

## 权限
- 标准评估器：读所有人，写 admin
- 指标库：读所有人，写 admin
- 编辑态按钮按 `user.role === 'admin'` 显隐

## 关键交互
- 权重编辑：数字输入（0-1），实时显示权重和，≠1 时保存按钮禁用 + 提示
- 指标编辑：skill_md 是 textarea（评分要求，自然语言）
- 删除指标：被标准评估器引用时后端 409，前端提示"请先从评估器移除"

## TODO
- [ ] 权重拖拽排序
- [ ] skill_md 编辑器（Markdown 预览）
- [ ] 指标导入/导出
- [ ] 评估器版本历史

## 协作守则
- 权重和校验前端做（双保险，后端也校验）。
- 普通用户进来是只读态，所有编辑按钮隐藏（非禁用）。
- skill_md 内容直接进 LLM prompt，编辑时提示"修改影响评分结果"。
