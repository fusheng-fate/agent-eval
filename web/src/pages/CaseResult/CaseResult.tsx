import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, ChevronUp, X } from "lucide-react";
import { runs, datasets } from "../../lib/api";
import { formatScore, cn } from "../../lib/utils";
import type { SelfCheckTraceStep, CaseOut, RunLogOut } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { ScoreBar } from "../../components/ui/ScoreBar";
import { EmptyState } from "../../components/ui/EmptyState";

export default function CaseResult() {
  const { id = "", caseId = "" } = useParams();
  const navigate = useNavigate();
  const [showOutput, setShowOutput] = useState(false);

  const { data: c, isLoading } = useQuery({
    queryKey: ["runs", "case", id, caseId],
    queryFn: () => runs.case(id, caseId),
  });

  // 数据集用例：补全维度 / 测试输入 / 预期结果（与报告用例透视一致）
  const { data: run } = useQuery({
    queryKey: ["runs", "get", id],
    queryFn: () => runs.get(id),
    enabled: !!id,
  });
  // 按需查单条数据集用例（补全维度/输入/预期）
  const { data: dsCase } = useQuery({
    queryKey: ["datasets", "cases", run?.dataset_id, c?.case_no],
    queryFn: () => datasets.casesBatch(run!.dataset_id, [c!.case_no!]),
    enabled: !!run?.dataset_id && !!c?.case_no,
  });
  const src: CaseOut | undefined = dsCase?.[0];

  // 本用例相关日志：拉全量任务日志后按 case_no 过滤（与评测执行页 terminal 风格一致）
  const { data: allLogs } = useQuery({
    queryKey: ["runs", id, "logs"],
    queryFn: () => runs.logs(id),
    enabled: !!id,
  });
  const caseLogs = useMemo(() => {
    const no = c?.case_no;
    if (!no) return [];
    return (allLogs || []).filter(
      (l) => l.message.includes(`用例 ${no}`) || l.message.includes(`[${no}]`)
    );
  }, [allLogs, c?.case_no]);

  if (isLoading) return <EmptyState title="加载中…" />;
  if (!c) return <EmptyState title="未找到该用例" />;

  const passed = (c.overall_score ?? 0) >= 4;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-[var(--color-muted)] hover:text-[var(--color-title)] cursor-pointer">
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-[20px] font-semibold text-[var(--color-title)] m-0">
          用例 {c.case_no || c.id.slice(0, 8)}
        </h1>
        <StatusBadge status={c.status} />
        <span
          className={`px-2.5 py-0.5 rounded-[var(--radius-full)] text-[11px] font-medium ${
            passed ? "bg-[#E7F7EC] text-[var(--color-success)]" : "bg-[#FDECEC] text-[var(--color-error)]"
          }`}
        >
          总分 {formatScore(c.overall_score)} / 100
        </span>
        {c.latency_sec != null && <span className="text-[11px] text-[var(--color-muted)]">耗时 {c.latency_sec}s</span>}
      </div>

      {/* 输入 / 预期 / 输出 */}
      <Card title="用例信息">
        <div className="space-y-4 text-[11px]">
          {src && (src.dimension_l1 || src.dimension_l2 || (src.tags && src.tags.length > 0)) && (
            <div className="flex flex-wrap items-center gap-2">
              {src.dimension_l1 && <DimTag label={`一级维度：${src.dimension_l1}`} />}
              {src.dimension_l2 && <DimTag label={`二级维度：${src.dimension_l2}`} />}
              {src.tags?.map((t, i) => <DimTag key={i} label={t} />)}
            </div>
          )}
          <div>
            <div className="text-[var(--color-muted)] text-[11px] mb-1">测试输入</div>
            <div className="whitespace-pre-wrap text-[var(--color-body)] bg-[var(--color-surface-alt)] rounded p-3 leading-relaxed">
              {src?.user_input || "（无）"}
            </div>
          </div>
          <div>
            <div className="text-[var(--color-muted)] text-[11px] mb-1">预期结果</div>
            <div className="whitespace-pre-wrap text-[var(--color-body)] bg-[var(--color-surface-alt)] rounded p-3 leading-relaxed">
              {src?.expected_gt || "（无）"}
            </div>
          </div>
          <div>
            <div className="text-[var(--color-muted)] text-[11px] mb-1">Agent 实际输出</div>
            <button
              onClick={() => setShowOutput((v) => !v)}
              className="text-[var(--link)] text-[11px] mb-1 inline-flex items-center gap-1 cursor-pointer"
            >
              {showOutput ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {showOutput ? "收起" : "展开"}
            </button>
            <div
              className={`whitespace-pre-wrap text-[var(--color-body)] bg-[var(--color-surface-alt)] rounded p-3 max-h-96 overflow-y-auto ${
                showOutput ? "" : "line-clamp-4"
              }`}
            >
              {c.agent_output || "（无输出）"}
            </div>
          </div>
          {c.target_trace && c.target_trace.length > 0 && (
            <div>
              <div className="text-[var(--color-muted)] text-[11px] mb-1">API 原始调用过程（{c.target_trace.length} 步）</div>
              <TraceView trace={c.target_trace} />
            </div>
          )}
        </div>
      </Card>

      {/* 标准指标 */}
      {c.standard_metrics && c.standard_metrics.length > 0 && (
        <Card title="标准指标（计入主分）">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
                <th className="py-2 px-3 font-medium">指标</th>
                <th className="py-2 px-3 font-medium">权重</th>
                <th className="py-2 px-3 font-medium">得分</th>
                <th className="py-2 px-3 font-medium">理由</th>
              </tr>
            </thead>
            <tbody>
              {c.standard_metrics.map((m) => (
                <tr key={m.metricId} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="py-3 px-3 text-[var(--color-title)]">{m.name}</td>
                  <td className="py-3 px-3">{m.weight}</td>
                  <td className="py-3 px-3 w-40">
                    <div className="flex items-center gap-2">
                      <ScoreBar score={m.score} className="flex-1" />
                      <span className="w-8 text-right">{formatScore(m.score)}</span>
                    </div>
                  </td>
                  <td className="py-3 px-3 text-[var(--color-body)] max-w-[280px]">{m.reason || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* 额外指标（单独计分，不进主分） */}
      {c.extra_metrics && c.extra_metrics.length > 0 && (
        <Card title="额外指标（单独计分，不计入主分）">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
                <th className="py-2 px-3 font-medium">指标</th>
                <th className="py-2 px-3 font-medium">得分</th>
                <th className="py-2 px-3 font-medium">理由</th>
              </tr>
            </thead>
            <tbody>
              {c.extra_metrics.map((m) => (
                <tr key={m.metricId} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="py-3 px-3 text-[var(--color-title)]">{m.name}</td>
                  <td className="py-3 px-3 w-40">
                    <div className="flex items-center gap-2">
                      <ScoreBar score={m.score} className="flex-1" />
                      <span className="w-8 text-right">{formatScore(m.score)}</span>
                    </div>
                  </td>
                  <td className="py-3 px-3 text-[var(--color-body)] max-w-[320px]">{m.reason || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* 简短评价 */}
      {c.brief_comment && (
        <Card title="简短评价">
          <p className="text-[11px] text-[var(--color-body)] m-0 leading-relaxed">{c.brief_comment}</p>
        </Card>
      )}

      {/* 失败归因（仅 failed 用例有值） */}
      {c.failure_attribution && (
        <Card title="失败归因">
          <div className="space-y-3 text-[11px]">
            <div className="flex items-center gap-2">
              <span className="text-[var(--color-muted)]">主归因：</span>
              <span className="px-2 py-0.5 rounded-[var(--radius-full)] text-[11px] font-medium bg-[#FDECEC] text-[var(--color-error)]">
                {c.failure_attribution.primary}
              </span>
            </div>
            {c.failure_attribution.items && c.failure_attribution.items.length > 0 && (
              <div className="space-y-2">
                {c.failure_attribution.items.map((it, i) => (
                  <div key={i} className="border border-[var(--color-border)] rounded-[var(--radius-form)] p-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[var(--color-title)] font-medium">{it.label || it.type}</span>
                      {it.type && <span className="text-[11px] text-[var(--color-muted)]">{it.type}</span>}
                    </div>
                    {it.reason && <p className="text-[var(--color-body)] mt-1 mb-0 leading-relaxed">{it.reason}</p>}
                    {it.evidence && <p className="text-[11px] text-[var(--color-muted)] mt-1 mb-0">证据：{it.evidence}</p>}
                  </div>
                ))}
              </div>
            )}
            {c.failure_attribution.reason && (
              <p className="text-[11px] text-[var(--color-body)] m-0 leading-relaxed">
                <span className="text-[var(--color-muted)]">总体说明：</span>
                {c.failure_attribution.reason}
              </p>
            )}
          </div>
        </Card>
      )}

      {/* 执行日志：与评测执行页「评测结果」terminal 风格一致，仅展示本用例相关日志 */}
      <Card title="执行日志">
        <CaseLogTerminal logs={caseLogs} />
      </Card>
    </div>
  );
}

// terminal 风格日志面板：展示本用例相关日志（按时间正序）
function CaseLogTerminal({ logs }: { logs: RunLogOut[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const logCount = logs.length;
  // 新日志到达时自动滚到底部
  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logCount]);

  const levelColor: Record<string, string> = {
    info: "text-[var(--color-body)]",
    success: "text-[var(--color-success)]",
    warn: "text-[var(--color-warning)]",
    error: "text-[var(--color-error)]",
  };

  return (
    <div className="rounded overflow-hidden border border-[var(--color-border)]">
      {/* terminal 标题栏 */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#1E1E1E]">
        <span className="w-3 h-3 rounded-full bg-[#FF5F57]" />
        <span className="w-3 h-3 rounded-full bg-[#FEBC2E]" />
        <span className="w-3 h-3 rounded-full bg-[#28C840]" />
        <span className="ml-2 text-[11px] text-[#8B8B8B] font-mono">case logs</span>
      </div>
      {/* 日志区域 */}
      <div
        ref={containerRef}
        className="bg-[#1E1E1E] p-3 max-h-[480px] overflow-y-auto font-mono text-[11px] leading-relaxed"
      >
        {logCount === 0 ? (
          <div className="text-[#6B6B6B]">暂无本用例相关日志</div>
        ) : (
          logs.map((l) => {
            const time = new Date(l.created_at).toLocaleTimeString("zh-CN", { hour12: false });
            const msgLines = l.message.split("\n");
            return (
              <div key={l.id} className="mb-1">
                <div className="flex gap-2">
                  <span className="text-[#6B6B6B] shrink-0">[{time}]</span>
                  <span className={cn("shrink-0 w-16 uppercase", levelColor[l.level] || "text-[var(--color-body)]")}>
                    {l.level}
                  </span>
                </div>
                <div className={cn("pl-[92px] break-all whitespace-pre-wrap", levelColor[l.level] || "text-[#D4D4D4]")}>
                  {msgLines.map((line, i) => (
                    <div key={i}>{line || " "}</div>
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function DimTag({ label }: { label: string }) {
  return (
    <span className="px-2 py-0.5 rounded-[var(--radius-full)] text-[11px] bg-[var(--color-surface-alt)] text-[var(--color-body)]">
      {label}
    </span>
  );
}

// API 原始调用过程：逐步展示请求/响应，失败步骤高亮，便于定位是哪一步出的问题
function TraceView({ trace }: { trace: SelfCheckTraceStep[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[var(--link)] text-[11px] mb-1 inline-flex items-center gap-1 cursor-pointer"
      >
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        {open ? "收起" : "展开"}
      </button>
      {open && (
        <div className="space-y-2">
          {trace.map((s, i) => <TraceStepRow key={i} step={s} idx={i} />)}
        </div>
      )}
    </div>
  );
}

function TraceStepRow({ step, idx }: { step: SelfCheckTraceStep; idx: number }) {
  const [open, setOpen] = useState(!!step.error);
  const isErr = !!step.error;
  return (
    <div className={cn("border rounded", isErr ? "border-[var(--color-error)]" : "border-[var(--color-border)]")}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left cursor-pointer"
      >
        <span className="text-[8px] text-[var(--color-muted)] w-4 shrink-0">{idx + 1}</span>
        <span className="px-1.5 py-0.5 rounded bg-[#E8F0FE] text-[var(--intl-blue)] text-[8px] font-medium shrink-0">{step.method}</span>
        <span className="text-[11px] font-mono text-[var(--color-title)] flex-1 truncate">{step.url}</span>
        {step.status !== null && (
          <span
            className={cn(
              "text-[8px] font-medium shrink-0",
              step.status >= 400 ? "text-[var(--color-error)]" : "text-[var(--color-success)]"
            )}
          >
            {step.status}
          </span>
        )}
        {isErr && <X size={14} className="text-[var(--color-error)] shrink-0" />}
        {open ? <ChevronUp size={14} className="text-[var(--color-muted)] shrink-0" /> : <ChevronDown size={14} className="text-[var(--color-muted)] shrink-0" />}
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 text-[11px]">
          {isErr && (
            <div>
              <div className="text-[var(--color-error)] font-medium mb-1">错误</div>
              <pre className="bg-[#FDECEC] rounded p-2 overflow-x-auto whitespace-pre-wrap break-words m-0">{step.error}</pre>
            </div>
          )}
          <TraceBlock label="请求头" data={step.headers} />
          <TraceBlock label="Query" data={step.query} />
          <TraceBlock label="请求体" data={step.body} />
          <TraceBlock label="响应" data={step.response} />
        </div>
      )}
    </div>
  );
}

function TraceBlock({ label, data }: { label: string; data: unknown }) {
  if (data === null || data === undefined || (typeof data === "object" && Object.keys(data as object).length === 0)) {
    return null;
  }
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <div>
      <div className="text-[var(--color-muted)] mb-1">{label}</div>
      <pre className="bg-[var(--color-surface-alt)] rounded p-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words m-0">{text}</pre>
    </div>
  );
}
