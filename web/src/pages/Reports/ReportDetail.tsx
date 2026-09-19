import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download, ChevronDown, ChevronUp } from "lucide-react";
import { reports, runs, datasets } from "../../lib/api";
import { formatNumber, formatNumber2, formatScore, cn, naturalCompare } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { KpiCard } from "../../components/ui/KpiCard";
import { ScoreBar } from "../../components/ui/ScoreBar";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { toast } from "../../components/ui/Toast";

type Tab = "overview" | "cases";

// 按需加载的用例行：测试输入/预期（数据集）+ 测试输出/打分理由（runs）
type CaseDetail = {
  user_input?: string;
  expected_gt?: string;
  agent_output?: string | null;
  brief_comment?: string | null;
};

export default function ReportDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  const [expandedFrc, setExpandedFrc] = useState<Record<string, boolean>>({});
  const [expandedDim, setExpandedDim] = useState<Record<string, boolean>>({});

  const { data: r, isLoading } = useQuery({
    queryKey: ["reports", "get", id],
    queryFn: () => reports.get(id),
  });
  const { data: run } = useQuery({
    queryKey: ["runs", "get", r?.run_id],
    queryFn: () => runs.get(r!.run_id),
    enabled: !!r?.run_id,
  });
  // 预建 case_no → { agent_output, brief_comment } 映射（报告 case_details 已含）
  const runDetailByCaseNo = new Map<string, CaseDetail>();
  for (const cd of r?.case_details || []) {
    if (!cd.caseNo) continue;
    runDetailByCaseNo.set(cd.caseNo, {
      agent_output: cd.agentOutput,
      brief_comment: cd.briefComment,
    });
  }

  if (isLoading) return <EmptyState title="加载中…" />;
  if (!r) return <EmptyState title="未找到报告" />;

  const s = r.summary || ({} as NonNullable<typeof r.summary>);
  const datasetId = run?.dataset_id;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-[var(--color-muted)] hover:text-[var(--color-title)] cursor-pointer">
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-[20px] font-semibold text-[var(--color-title)] m-0">{r.task_name}</h1>
        <Button
          variant="outline"
          className="ml-auto h-9"
          onClick={() => reports.exportHtml(id).catch((e) => toast("error", e.message))}
        >
          <Download size={16} /> 导出 HTML
        </Button>
      </div>

      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {(["overview", "cases"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2.5 text-[11px] border-b-2 -mb-px cursor-pointer",
              tab === t ? "border-[var(--brand)] text-[var(--brand)] font-medium" : "border-transparent text-[var(--color-body)]"
            )}
          >
            {t === "overview" ? "总览" : "用例透视"}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <KpiCard label="加权主分" value={formatScore(s.overallScore)} />
            <KpiCard label="用例总数" value={formatNumber(s.total)} />
            <KpiCard label="失败用例" value={formatNumber(s.failed)} tone={s.failed ? "error" : "default"} />
            <KpiCard label="Token 消耗" value={formatNumber(s.tokenUsage)} />
            <KpiCard label="平均时延(s)" value={formatNumber2(s.avgLatencySec)} />
          </div>

          {r.standard_metric_averages && r.standard_metric_averages.length > 0 && (
            <Card title="标准指标均分">
              <div className="space-y-3">
                {r.standard_metric_averages.map((m) => (
                  <div key={m.metricId} className="flex items-center gap-3">
                    <span className="shrink-0 text-[11px] text-[var(--color-title)]">{m.name}</span>
                    <span className="shrink-0 text-[11px] text-[var(--color-muted)]">权重 {m.weight}</span>
                    <ScoreBar score={m.avgScore} className="flex-1 min-w-0" />
                    <span className="shrink-0 w-16 text-[11px] text-right">{formatScore(m.avgScore)} <span className="text-[var(--color-muted)] text-[11px]">/ 100</span></span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {r.extra_metric_averages && r.extra_metric_averages.length > 0 && (
            <Card title="额外指标均分（单独计分）">
              <div className="space-y-3">
                {r.extra_metric_averages.map((m) => (
                  <div key={m.metricId} className="flex items-center gap-3">
                    <span className="shrink-0 text-[11px] text-[var(--color-title)]">{m.name}</span>
                    <ScoreBar score={m.avgScore} className="flex-1 min-w-0" />
                    <span className="shrink-0 w-16 text-[11px] text-right">{formatScore(m.avgScore)} <span className="text-[var(--color-muted)] text-[11px]">/ 100</span></span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {r.failure_root_causes && r.failure_root_causes.length > 0 && (
            <Card title="失败归因分布">
              <div className="space-y-3">
                {r.failure_root_causes.map((f) => {
                  const total = r.failure_root_causes!.reduce((s, x) => s + x.count, 0);
                  const pct = total ? f.count / total : 0;
                  const fCases = f.cases || [];
                  const expanded = !!expandedFrc[f.category];
                  return (
                    <div key={f.category}>
                      <div className="flex items-center gap-4">
                        <span className="w-28 text-[11px] text-[var(--color-title)] truncate">{f.category}</span>
                        <div className="flex-1 h-2 rounded-[var(--radius-full)] bg-[var(--color-surface-alt)] overflow-hidden">
                          <div className="h-full rounded-[var(--radius-full)] bg-[var(--color-error)]" style={{ width: `${pct * 100}%` }} />
                        </div>
                        <span className="w-24 text-[11px] text-right text-[var(--color-body)]">
                          {f.count} 例 · {Math.round(pct * 100)}%
                        </span>
                        {fCases.length > 0 && (
                          <button
                            onClick={() => setExpandedFrc((prev) => ({ ...prev, [f.category]: !prev[f.category] }))}
                            className="text-[var(--link)] text-[11px] inline-flex items-center gap-1 cursor-pointer shrink-0"
                          >
                            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            {expanded ? "收起" : `查看 ${fCases.length} 条`}
                          </button>
                        )}
                      </div>
                      {expanded && fCases.length > 0 && (
                        <div className="mt-2 ml-4 border-l-2 border-[var(--color-border)] pl-3">
                          <LazyCaseTable
                            datasetId={datasetId}
                            caseNos={fCases.map((c) => c.caseNo)}
                            baseRows={fCases.map((c) => ({ caseNo: c.caseNo, status: c.status, overallScore: c.overallScore }))}
                            runDetailByCaseNo={runDetailByCaseNo}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {r.dimension_summary && r.dimension_summary.length > 0 && (
            <Card title="维度汇总">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
                    <th className="py-2.5 px-3 font-medium">维度 L1</th>
                    <th className="py-2.5 px-3 font-medium">维度 L2</th>
                    <th className="py-2.5 px-3 font-medium">用例</th>
                    <th className="py-2.5 px-3 font-medium">通过</th>
                    <th className="py-2.5 px-3 font-medium">失败</th>
                    <th className="py-2.5 px-3 font-medium">均分</th>
                    <th className="py-2.5 px-3 font-medium">明细</th>
                  </tr>
                </thead>
                <tbody>
                  {r.dimension_summary.map((d) => {
                    const dimCases = d.cases || [];
                    const key = `${d.l1}|${d.l2}`;
                    const expanded = !!expandedDim[key];
                    return (
                      <>
                        <tr key={key} className="border-b border-[var(--color-border)] last:border-0">
                          <td className="py-3 px-3 text-[var(--color-title)]">{d.l1}</td>
                          <td className="py-3 px-3">{d.l2}</td>
                          <td className="py-3 px-3">{d.total}</td>
                          <td className="py-3 px-3 text-[var(--color-success)]">{d.passed}</td>
                          <td className="py-3 px-3 text-[var(--color-error)]">{d.failed}</td>
                          <td className="py-3 px-3">{formatScore(d.avgScore)}</td>
                          <td className="py-3 px-3">
                            {dimCases.length > 0 && (
                              <button
                                onClick={() => setExpandedDim((prev) => ({ ...prev, [key]: !prev[key] }))}
                                className="text-[var(--link)] text-[11px] inline-flex items-center gap-1 cursor-pointer"
                              >
                                {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                {expanded ? "收起" : `查看 ${dimCases.length} 条`}
                              </button>
                            )}
                          </td>
                        </tr>
                        {expanded && dimCases.length > 0 && (
                          <tr key={`${key}-detail`}>
                            <td colSpan={7} className="py-2 px-3 bg-[var(--color-surface-alt)]">
                              <LazyCaseTable
                                datasetId={datasetId}
                                caseNos={dimCases.map((c) => c.caseNo)}
                                baseRows={dimCases.map((c) => ({ caseNo: c.caseNo, status: c.status, overallScore: c.overallScore }))}
                                runDetailByCaseNo={runDetailByCaseNo}
                              />
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </Card>
          )}
        </div>
      ) : (
        <CasePivot reportId={r.id} datasetId={datasetId} />
      )}
    </div>
  );
}

/** 懒加载用例表格：展开时按 case_no 批量查数据集用例，合并 runs 已有数据后渲染（前端分页）。 */
function LazyCaseTable({
  datasetId,
  caseNos,
  baseRows,
  runDetailByCaseNo,
}: {
  datasetId: string | undefined;
  caseNos: string[];
  baseRows: Array<{ caseNo: string; status: string; overallScore: number | null }>;
  runDetailByCaseNo: Map<string, CaseDetail>;
}) {
  const { data: dsCases, isLoading } = useQuery({
    queryKey: ["datasets", "casesBatch", datasetId, caseNos.join(",")],
    queryFn: () => datasets.casesBatch(datasetId!, caseNos),
    enabled: !!datasetId && caseNos.length > 0,
  });

  // 合并：runs 数据（agent_output/brief_comment）+ 数据集数据（user_input/expected_gt）
  const dsMap = new Map((dsCases || []).map((c) => [c.case_no, c]));
  const rows = baseRows
    .map((b) => {
      const ds = dsMap.get(b.caseNo);
      const run = runDetailByCaseNo.get(b.caseNo);
      return {
        ...b,
        user_input: ds?.user_input,
        expected_gt: ds?.expected_gt,
        agent_output: run?.agent_output,
        brief_comment: run?.brief_comment,
      };
    })
    .sort((a, b) => naturalCompare(a.caseNo, b.caseNo));

  if (isLoading) {
    return <div className="py-4 text-center text-[11px] text-[var(--color-muted)]">加载中…</div>;
  }

  return <CaseTable rows={rows} />;
}

function CasePivot({ reportId, datasetId }: { reportId: string; datasetId: string | undefined }) {
  const { data: r } = useQuery({ queryKey: ["reports", "get", reportId], queryFn: () => reports.get(reportId) });

  const cases = r?.case_details || [];
  const sorted = [...cases].sort((a, b) => naturalCompare(a.caseNo || "", b.caseNo || ""));
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
  const total = sorted.length;
  const paged = sorted.slice((page - 1) * pageSize, page * pageSize);
  const [sel, setSel] = useState(0);
  const cur = paged[sel];

  // 按需加载当前选中用例的数据集信息
  const { data: curSrc, isLoading: srcLoading } = useQuery({
    queryKey: ["datasets", "casesBatch", datasetId, cur?.caseNo],
    queryFn: () => datasets.casesBatch(datasetId!, [cur!.caseNo]),
    enabled: !!datasetId && !!cur?.caseNo,
  });
  const src = curSrc?.[0];

  useEffect(() => {
    setPage(1);
    setSel(0);
  }, [pageSize]);

  if (!r) return <EmptyState title="加载中…" />;
  if (cases.length === 0) return <EmptyState title="无用例明细" />;

  return (
    <div className="flex gap-6">
      <div className="w-64 shrink-0 border border-[var(--color-border)] rounded-[var(--radius-card)] bg-white flex flex-col max-h-[70vh]">
        <div className="flex-1 overflow-y-auto">
          {paged.map((c, i) => (
            <button
              key={c.caseId}
              onClick={() => setSel(i)}
              className={cn(
                "w-full text-left px-4 py-3 border-b border-[var(--color-border)] last:border-0 cursor-pointer",
                i === sel ? "bg-[var(--color-hover)]" : "hover:bg-[var(--color-hover)]"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-[var(--color-title)] font-medium truncate">{c.caseNo || c.caseId.slice(0, 8)}</span>
                <span className={cn("text-[11px] shrink-0", c.status === "passed" ? "text-[var(--color-success)]" : "text-[var(--color-error)]")}>
                  {c.status === "passed" ? "通过" : "失败"}
                </span>
              </div>
              <div className="text-[11px] text-[var(--color-muted)] mt-0.5">
                主分 {formatScore(c.overallScore)}
                {cur?.latencySec != null && <span className="ml-2">{cur.latencySec}s</span>}
              </div>
            </button>
          ))}
        </div>
        <div className="border-t border-[var(--color-border)] p-2">
          <Pagination
            page={page}
            size={pageSize}
            total={total}
            onChange={(p) => { setPage(p); setSel(0); }}
            sizeOptions={PAGE_SIZE_OPTIONS}
            onSizeChange={setPageSize}
          />
        </div>
      </div>

      <div className="flex-1 min-w-0 space-y-4">
        {cur && (
          <>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-[var(--color-title)] font-medium">用例 {cur.caseNo || cur.caseId.slice(0, 8)}</span>
              <StatusBadge status={cur.status} />
              <span className="text-[11px] text-[var(--color-muted)]">主分 {formatScore(cur.overallScore)} / 100</span>
              {cur?.tokenUsage != null && <span className="text-[11px] text-[var(--color-muted)]">Token {formatNumber(cur.tokenUsage)}</span>}
              {cur?.latencySec != null && <span className="text-[11px] text-[var(--color-muted)]">耗时 {cur.latencySec}s</span>}
            </div>

            {/* 用例信息：输入 / 预期 / 维度 / 标签 */}
            <Card title="用例信息">
              <div className="space-y-3 text-[11px]">
                {srcLoading ? (
                  <div className="text-[var(--color-muted)]">加载中…</div>
                ) : (
                  <>
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
                  </>
                )}
              </div>
            </Card>

            {/* Agent 实际输出（可折叠） */}
            {cur?.agentOutput && <AgentOutput text={cur.agentOutput} />}

            {/* 标准指标 */}
            {cur.standardMetrics && cur.standardMetrics.length > 0 && (
              <Card title="标准指标">
                <div className="space-y-3">
                  {cur.standardMetrics.map((m) => (
                    <div key={m.metricId}>
                      <div className="flex items-center gap-3">
                        <span className="shrink-0 text-[11px] text-[var(--color-title)]">{m.name}</span>
                        <span className="shrink-0 text-[11px] text-[var(--color-muted)]">权重 {m.weight}</span>
                        <ScoreBar score={m.score} className="flex-1 min-w-0" />
                        <span className="shrink-0 w-16 text-[11px] text-right">{formatScore(m.score)} <span className="text-[var(--color-muted)] text-[11px]">/ 100</span></span>
                      </div>
                      {m.reason && <p className="text-[11px] text-[var(--color-muted)] mt-1 mb-0 pl-0">{m.reason}</p>}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {/* 额外指标 */}
            {cur.extraMetrics && cur.extraMetrics.length > 0 && (
              <Card title="额外指标（单独计分）">
                <div className="space-y-3">
                  {cur.extraMetrics.map((m) => (
                    <div key={m.metricId}>
                      <div className="flex items-center gap-3">
                        <span className="shrink-0 text-[11px] text-[var(--color-title)]">{m.name}</span>
                        <ScoreBar score={m.score} className="flex-1 min-w-0" />
                        <span className="shrink-0 w-16 text-[11px] text-right">{formatScore(m.score)} <span className="text-[var(--color-muted)] text-[11px]">/ 100</span></span>
                      </div>
                      {m.reason && <p className="text-[11px] text-[var(--color-muted)] mt-1 mb-0 pl-0">{m.reason}</p>}
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {/* 简短评价 */}
            {cur.briefComment && (
              <Card title="简短评价">
                <p className="text-[11px] text-[var(--color-body)] m-0">{cur.briefComment}</p>
              </Card>
            )}

            {/* 失败归因 */}
            {cur.failureAttribution && (
              <Card title="失败归因">
                <div className="space-y-3 text-[11px]">
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--color-muted)]">主归因：</span>
                    <span className="px-2 py-0.5 rounded-[var(--radius-full)] text-[11px] font-medium bg-[#FDECEC] text-[var(--color-error)]">
                      {cur.failureAttribution.primary}
                    </span>
                  </div>
                  {cur.failureAttribution.items && cur.failureAttribution.items.length > 0 && (
                    <div className="space-y-2">
                      {cur.failureAttribution.items.map((it, i) => (
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
                  {cur.failureAttribution.reason && (
                    <p className="text-[var(--color-body)] m-0 leading-relaxed">
                      <span className="text-[var(--color-muted)]">总体说明：</span>
                      {cur.failureAttribution.reason}
                    </p>
                  )}
                </div>
              </Card>
            )}

            {/* 错误信息 */}
            {cur?.errorMsg && (
              <Card title="错误信息">
                <p className="text-[var(--color-error)] m-0 whitespace-pre-wrap">{cur.errorMsg}</p>
              </Card>
            )}
          </>
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

// 用例表格：表头 用例/状态/加权分数/测试输入/预期结果/测试输出/打分理由，长文本截断可点开
function CaseTable({ rows }: { rows: Array<{ caseNo: string; status: string; overallScore: number | null; user_input?: string | null; expected_gt?: string | null; agent_output?: string | null; brief_comment?: string | null }> }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const PAGE_SIZE_OPTIONS = [10, 20, 50];
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const cur = Math.min(page, pages);
  const paged = rows.slice((cur - 1) * pageSize, cur * pageSize);
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr className="text-left text-[var(--color-muted)] border-b border-[var(--color-border)]">
              <th className="py-2 px-2 font-medium whitespace-nowrap">用例</th>
              <th className="py-2 px-2 font-medium whitespace-nowrap">状态</th>
              <th className="py-2 px-2 font-medium whitespace-nowrap">加权分数</th>
              <th className="py-2 px-2 font-medium">测试输入</th>
              <th className="py-2 px-2 font-medium">预期结果</th>
              <th className="py-2 px-2 font-medium">测试输出</th>
              <th className="py-2 px-2 font-medium">打分理由</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((r, i) => (
              <tr key={i} className="border-b border-[var(--color-border)] last:border-0 align-top">
                <td className="py-2 px-2 text-[var(--color-title)] font-medium whitespace-nowrap">{r.caseNo}</td>
                <td className="py-2 px-2 whitespace-nowrap">
                  <span className={cn(r.status === "passed" ? "text-[var(--color-success)]" : r.status === "failed" ? "text-[var(--color-error)]" : "text-[var(--color-muted)]")}>
                    {r.status === "passed" ? "通过" : r.status === "failed" ? "失败" : r.status}
                  </span>
                </td>
                <td className="py-2 px-2 whitespace-nowrap">{formatScore(r.overallScore)}</td>
                <td className="py-2 px-2 min-w-[160px]"><CellText value={r.user_input} /></td>
                <td className="py-2 px-2 min-w-[160px]"><CellText value={r.expected_gt} /></td>
                <td className="py-2 px-2 min-w-[160px]"><CellText value={r.agent_output} /></td>
                <td className="py-2 px-2 min-w-[160px]"><CellText value={r.brief_comment} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        page={cur}
        size={pageSize}
        total={total}
        onChange={setPage}
        sizeOptions={PAGE_SIZE_OPTIONS}
        onSizeChange={(s) => { setPageSize(s); setPage(1); }}
      />
    </div>
  );
}

// 表格单元格长文本：默认截断 2 行，可点开看全文
function CellText({ value }: { value?: string | null }) {
  const [open, setOpen] = useState(false);
  const text = (value ?? "").trim();
  if (!text) return <span className="text-[var(--color-muted)]">-</span>;
  return (
    <span
      className={cn("whitespace-pre-wrap break-all", !open && "line-clamp-2 cursor-pointer")}
      onClick={() => text.length > 60 && setOpen((v) => !v)}
    >
      {text}
    </span>
  );
}

// 把 LLM 输出美化：JSON 则格式化 + 语法高亮，纯文本原样展示。
function AgentOutput({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const trimmed = text.trim();
  const isJson = (trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"));
  let pretty = text;
  if (isJson) {
    try {
      pretty = JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      /* 非合法 JSON，按原文展示 */
    }
  }
  return (
    <Card
      title="Agent 实际输出"
      extra={
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-[var(--link)] text-[11px] inline-flex items-center gap-1 cursor-pointer"
        >
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {open ? "收起" : "展开"}
        </button>
      }
    >
      {isJson ? (
        <pre
          className={cn(
            "overflow-auto font-mono text-[11px] leading-relaxed text-[var(--color-body)] bg-[var(--color-surface-alt)] rounded p-3 m-0",
            open ? "max-h-96" : "max-h-56"
          )}
        >
          <JsonHighlight value={pretty} />
        </pre>
      ) : (
        <div
          className={cn(
            "whitespace-pre-wrap text-[11px] leading-relaxed text-[var(--color-body)] bg-[var(--color-surface-alt)] rounded p-3 overflow-y-auto",
            open ? "max-h-96" : "line-clamp-4"
          )}
        >
          {text}
        </div>
      )}
    </Card>
  );
}

// 轻量 JSON 语法高亮：键 / 字符串 / 数字 / 布尔 / null 分色。
function JsonHighlight({ value }: { value: string }) {
  const parts = value.split(/("(?:\\.|[^"\\])*"(?=\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (!p) return null;
        if (/^"(?:\\.|[^"\\])*"$/.test(p)) {
          const isKey = /:\s*$/.test(p);
          return (
            <span key={i} className={isKey ? "text-[var(--intl-blue)]" : "text-[var(--color-success)]"}>
              {p}
            </span>
          );
        }
        if (/^\b(?:true|false|null)\b$/.test(p)) return <span key={i} className="text-[var(--color-warning)]">{p}</span>;
        if (/^-?\d/.test(p)) return <span key={i} className="text-[var(--color-error)]">{p}</span>;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}
