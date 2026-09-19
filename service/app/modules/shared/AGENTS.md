# shared 模块

## 职责
跨模块共享的通用模型。当前仅 `Msg`（通用响应）。

## 文件
- `schemas.py` — Msg

## 内容
```python
class Msg(BaseModel):
    message: str
    ok: bool = True
```

## 使用
所有模块的删除/更新/自检等"操作类"接口返回 `Msg`。

## 协作守则
- 新增跨模块共享模型放这里（如通用分页响应、通用错误结构）。
- 仅模块内部用的模型放各自 `schemas.py`，不放这里。
- `Msg` 字段变更影响所有模块，改前全局搜索引用。
