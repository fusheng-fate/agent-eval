import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileBarChart } from "lucide-react";
import { runs, datasets } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import type { CaseResultOut, CaseOut } from "../../lib/types";
import { formatPercent, formatScore, formatDateTime } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { KpiCard } from "../../components/ui/KpiCard";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { toast } from "../../components/ui/Toast";

const ACTIVE = ["pending", "running", "paused"];

export default function RunDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user, isAdmin } = useAuth();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

  const { data: run, isLoading } = useQuery({
    queryKey: ["runs", "get", id],
    queryFn: () => runs.get(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && ACTIVE.includes(s) ? 2000 : false;
    },
  });

  const { data: casesPage, isLoading: casesLoading } = useQuery({
    queryKey: ["runs", "cases", id, page, pageSize],
    queryFn: () => runs.casesPaged(id, { page, page_size: pageSize }),
    enabled: !!run,
    refetchInterval: run && ACTIVE.includes(run.status) ? 2000 : false,
  });
  const cases = casesPage?.items ?? [];
  const casesTotal = casesPage?.total ?? 0;

  // 数据集用例（按当前页 case_no 批量查），映射出「测试输入」
  const pageCaseNos = cases.map((c) => c.case_no).filter(Boolean) as string[];
  const { data: dsCases } = useQuery({
    queryKey: ["datasets", "cases", run?.dataset_id, "batch", pageCaseNos.join(",")],
    queryFn: () => datasets.casesBatch(run!.dataset_id, pageCaseNos),
    enabled: !!run?.dataset_id && pageCaseNos.length > 0,
  });
  const dsByCaseNo = new Map<string, CaseOut>(((dsCases) || []).map((c) => [c.case_no, c]));

  // 每页数量变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [pageSize]);

  const act = useMutation({
    mutationFn: (op: "pause" | "resume" | "stop") =>
      op === "pause" ? runs.pause(id) : op === "resume" ? runs.resume(id) : runs.stop(id),
    onSuccess: () => {
      toast("success", "操作成功");
      qc.invalidateQueries({ queryKey: ["runs", "get", id] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "操作失败"),
  });

  if (isLoading || !run) return <EmptyState title="加载中…" />;

  const canOperate = isAdmin || run.owner_id === user?.id;
  const passRate = run.total_cases ? run.passed_cases / run.total_cases : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-[var(--color-muted)] hover:text-[var(--color-title)] cursor-pointer">
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-[20px] font-semibold text-[var(--color-title)] m-0">{run.task_name}</h1>
        <StatusBadge status={run.status} />
      </div>

      {/* 统计条 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="进度" value={`${run.done_cases}/${run.total_cases}`} />
        <KpiCard label="通过率" value={formatPercent(passRate)} tone="success" />
        <KpiCard label="加权得分" value={formatScore(run.overall_score)} />
        <KpiCard label="创建时间" value={<span className="text-[13px]">{formatDateTime(run.created_at)}</span>} />
      </div>

      <Card
        title="逐用例结果"
        extra={
          <div className="flex items-center gap-2">
            {canOperate && ACTIVE.includes(run.status) && (
              <>
                {run.status !== "paused" && (
                  <Button variant="outline" className="h-9" onClick={() => act.mutate("pause")}>暂停</Button>
                )}
                {run.status === "paused" && (
                  <Button variant="outline" className="h-9" onClick={() => act.mutate("resume")}>继续</Button>
                )}
                <Button variant="outline" className="h-9 text-[var(--color-error)]" onClick={() => act.mutate("stop")}>
                  停止
                </Button>
              </>
            )}
            <Button variant="outline" className="h-9" onClick={() => runs.export(id, "eval").catch((e) => toast("error", e.message))}>
              <Download size={16} /> 导出结果
            </Button>
            {run.status === "done" && run.report_id && (
              <Button className="h-9" onClick={() => navigate(`/reports/${run.report_id}`)}>
                <FileBarChart size={16} /> 查看报告
              </Button>
            )}
          </div>
        }
      >
        {casesLoading ? (
          <EmptyState title="加载中…" />
        ) : !cases || cases.length === 0 ? (
          <EmptyState title="暂无用例结果" />
        ) : (
          <>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
                  <th className="py-2.5 px-3 font-medium">用例编号</th>
                  <th className="py-2.5 px-3 font-medium">分数</th>
                  <th className="py-2.5 px-3 font-medium">状态</th>
                  <th className="py-2.5 px-3 font-medium">测试输入</th>
                  <th className="py-2.5 px-3 font-medium">预期结果</th>
                  <th className="py-2.5 px-3 font-medium">测试输出</th>
                  <th className="py-2.5 px-3 font-medium">打分理由</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c: CaseResultOut) => {
                  const src = dsByCaseNo.get(c.case_no || "");
                  return (
                    <tr
                      key={c.id}
                      className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-hover)] cursor-pointer"
                      onClick={() => navigate(`/runs/${id}/cases/${c.case_id}`)}
                    >
                      <td className="py-3 px-3 text-[var(--color-title)] font-medium whitespace-nowrap">{c.case_no || c.id.slice(0, 8)}</td>
                      <td className="py-3 px-3">{c.status === "error" ? "-" : formatScore(c.overall_score)}</td>
                      <td className="py-3 px-3"><StatusBadge status={c.status === "running" && !c.exec_started_at ? "queued" : c.status} /></td>
                      <td className="py-3 px-3 text-[var(--color-body)] max-w-[240px] truncate" title={src?.user_input || ""}>{src?.user_input || "-"}</td>
                      <td className="py-3 px-3 text-[var(--color-body)] max-w-[240px] truncate" title={src?.expected_gt || ""}>{src?.expected_gt || "-"}</td>
                      <td className="py-3 px-3 text-[var(--color-body)] max-w-[240px] truncate" title={c.agent_output || ""}>{c.agent_output || "-"}</td>
                      {c.status === "error" ? (
                        <td className="py-3 px-3 text-[var(--color-error)] max-w-[320px] truncate" title={c.error_msg || ""}>
                          {c.error_msg ? c.error_msg.split("\n")[0].slice(0, 80) : "-"}
                        </td>
                      ) : (
                        <td className="py-3 px-3 text-[var(--color-body)] max-w-[320px] truncate" title={c.brief_comment || ""}>{c.brief_comment || "-"}</td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            size={pageSize}
            total={casesTotal}
            onChange={setPage}
            sizeOptions={PAGE_SIZE_OPTIONS}
            onSizeChange={setPageSize}
          />
          </>
        )}
      </Card>
    </div>
  );
}
