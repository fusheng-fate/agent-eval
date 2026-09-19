# agent-eval

## 竞态一：resume 重复执行/打分
前置条件（缺一个都触发不了）
条件	原因	默认值
被测 Agent 要「慢」	竞态窗口 = [pause, worker 跑完]，Agent 越快窗口越窄	需自备慢端点
WORKER_COUNT ≥ 2	需要第二个执行 worker 去抢被 reset 的 pending	12 ✓
target_concurrency ≥ 2	第二个 worker 要能抢到槽位；=1 时它会 SlotBusy 让出，不会真正重复	3 ✓
评分侧还需 CONCURRENCY_MODEL ≥ 2	需要第二个评分 worker	5 ✓
关键点：target_concurrency 必须是 ≥2。因为 A 在整个 Agent 调用期间都持有槽位（call_target_multi_turn 里 _acquire 包住 call_target，finally 才 _release），若上限是 1，B 抢槽会 SlotBusy 让出，反而不重复。

触发执行重复
1. 起一个睡 60 秒的慢"被测 Agent"（顺便打印每次请求，便于数次数）：

python
12 lines
Copy
# slow_target.py

from http.server import BaseHTTPRequestHandler, HTTPServer

import time

class H(BaseHTTPRequestHandler):

    def do_POST(self):

        time.sleep(60)

        print(">>> 收到一次被测调用", flush=True)

        b = b'{"answer":"ok","confidence":1.0,"sources":[]}'

        self.send_response(200); self.send_header("Content-Type","application/json")

        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a): pass

HTTPServer(("127.0.0.1", 9100), H).serve_forever()
把流程模板里 apis[0].url 指到 http://127.0.0.1:9100（单步骤即可，final_extract 随便配一个字段）。

2. 起一个 1 条 case 的 run，盯着日志或 DB，看到 开始执行用例 C001（worker.py:344）确认 A 已进入执行。

3. 立刻连着调两个接口（在 60s 窗口内，越早越好）：

bash
2 lines
Copy
curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/pause  -H "Authorization: Bearer $TOKEN"

curl -X POST http://127.0.0.1:8000/api/runs/{run_id}/resume -H "Authorization: Bearer $TOKEN"
4. 验证——两种方式任选：

看慢端点日志：>>> 收到一次被测调用 出现两次 = 重复执行坐实。
查日志表：
sql
4 lines
Copy
SELECT created_at, message FROM run_logs

WHERE run_id = '{run_id}' AND message LIKE '%开始执行用例%'

ORDER BY created_at;

-- 同一 case_no 出现两行 → 重复执行
触发评分重复
同一条竞态，只是窗口从「执行」换成「评分」。执行要快（先让 case 到 executed），评分要慢：

被测 Agent 用快的（正常 mock 即可）；把评测 LLM（配置中心 llm.base_url / llm.model）指到一个睡 30 秒再返回合法打分 JSON 的桩。
run 跑起来 → case 先 executed → 评分 worker 抢到变 scoring。
在 scoring 期间立刻 pause + resume（resume 会把 scoring→executed 重置）。
验证：LLM 桩收到两次打分请求，或 run_logs 里同一 case 出现两次「评分完成」。
竞态二：attempt 计数器
方向 A：正常 case 无限重评
评测 LLM 指到一个必超时的端点（或把 llm.timeout 调得很小、指向一个睡 60s 的桩，让它必超时）。
执行侧保持正常（被测 Agent 正常返回）。
run 一条 case：执行成功 → attempt=1 → 评分超时 → 回 executed → 再抢 → 再超时 → ……
验证：反复查这条 case 的状态，会在 executed ↔ scoring 之间振荡不停；run_logs 不断新增评分相关日志；attempt 永远停在 1；run 永远不完成。
sql
2 lines
Copy
SELECT status, attempt, finished_at FROM case_results WHERE id = '{cr_id}';

-- 隔几秒查一次，看它在 executed/scoring 之间来回，attempt 一直是 1
方向 B：attempt≥3 时一次超时就 error
自然触发（3 次 SlotBusy 让出）不好控，最稳的是直接改库验证：

让一条 case 正常执行到 executed（此时 attempt=1）。
手动抬高 attempt：
sql
1 line
Copy
UPDATE case_results SET attempt = 3 WHERE id = '{cr_id}' AND status = 'executed';
保持评测 LLM 必超时。
验证：评分 worker 抢到后，第一次超时就命中 attempt < 3 为 False → 直接 status='error'、finished_at 被填上，不再回 executed，无重试。
sql
2 lines
Copy
SELECT status, attempt, finished_at, error_msg FROM case_results WHERE id = '{cr_id}';

-- 应是 status=error 且 finished_at 非空，而不是回到 executed