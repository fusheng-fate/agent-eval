# Execution 页面（评测执行）

## 职责
评测执行（v3.0 第 4 步）：**页签式**——评估器选择 / 数据集选择 / 测试执行流程（选模板+调参）/ 自检（执行+评测）/ 测试执行 / 评测结果。原 apiChain 链路编辑并入"测试执行流程"页签（选模板而非从零编辑）。

## 路由
`/execution`

## 消费接口
| 函数 | 接口 | 说明 |
|------|------|------|
| `evaluators.getStandard` | GET `/evaluators/standard` | 标准评估器（必选默认） |
| `metrics.list` | GET `/metrics` | 额外指标候选（可选勾选） |
| `datasets.list` | GET `/datasets` | 数据集选择（全量，可搜） |
| `datasets.preview` | GET `/datasets/{id}/preview` | 数据集前 5 行核验 |
| `flowTemplates.list` | GET `/flow-templates` | 模板列表（环境选择） |
| `flowTemplates.get` | GET `/flow-templates/{id}` | 模板详情（含 param_perms） |
| `runs.selfcheckExec` | POST `/runs/selfcheck/exec` | 执行自检 |
| `runs.selfcheckEval` | POST `/runs/selfcheck/eval` | 评测自检 |
| `runs.create` | POST `/runs` | 创建任务（单用户单活跃 P25） |
| `runs.get` | GET `/runs/{id}` | 进度（创建后轮询） |

## 页签流程
1. **评估器选择**：标准评估器（固定必选，显示指标+权重）+ 额外指标（可选勾选，单独计分）
2. **数据集选择**：从全量数据集选（可搜），显示前 5 行核验
3. **测试执行流程**：选模板（环境选择）→ 按 param_perms 显示可编辑参数（普通用户仅 user_editable=True 的）→ 调参
4. **自检**：
   - 执行自检（取第一个用例跑链路，测被测 Agent 连通性）
   - 评测自检（测 LLM 接口）
5. **测试执行**：确认配置 → 创建任务（P25：已有活跃任务则提示）→ 跳任务详情
6. **评测结果**：创建后显示进度（轮询），完成后跳报告

## 关键交互
- **额外指标**：勾选的指标单独计分，不进主分（UI 要提示）
- **模板参数**：按 param_perms 控制输入框可编辑性（普通用户仅 user_editable 的）
- **自检**：两个自检都通过才允许"测试执行"按钮启用
- **创建任务**：P25 单用户单活跃，已有任务时后端 409，前端提示"已有任务进行中"

## 权限
- 标准评估器/数据集/模板：所有登录用户可读
- 额外指标：所有登录用户可勾选
- 模板参数：普通用户仅 user_editable 的可改
- 创建任务：所有登录用户（受 P25 限制）

## TODO
- [ ] 页签步骤指示器（1-6 步进度）
- [ ] 自检结果详情（执行自检返回的连通性信息）
- [ ] 参数校验（必填/类型）
- [ ] 创建后自动跳 RunDetail

## 协作守则
- 页签状态用 useState 管理（当前步骤 + 各步数据）。
- 额外指标和标准评估器要视觉区分（额外是"附加"，不进主分）。
- 模板参数编辑要按 param_perms 动态渲染（不同模板不同参数）。
