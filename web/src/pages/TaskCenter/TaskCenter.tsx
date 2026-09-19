import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Plus, Eye, FileBarChart, Database, Download, RefreshCw } from "lucide-react";
import { dashboard, runs, datasets, flowTemplates } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import type { RunOut, DatasetOut } from "../../lib/types";
import { formatNumber, formatDateTime } from "../../lib/utils";

/** 时间三行显示：年 / 月日 / 时分 */
function TimeCell({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="text-[var(--color-muted)]">-</span>;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return <span className="text-[var(--color-muted)]">{iso}</span>;
  const p = (x: number) => String(x).padStart(2, "0");
  return (
    <div className="leading-tight text-[var(--color-muted)]">
      <div>{d.getFullYear()}</div>
      <div>{p(d.getMonth() + 1)}-{p(d.getDate())}</div>
      <div>{p(d.getHours())}:{p(d.getMinutes())}</div>
    </div>
  );
}
import { Card } from "../../components/ui/Card";
import { KpiCard } from "../../components/ui/KpiCard";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Button } from "../../components/ui/Button";
import { Input, Select } from "../../components/ui/Input";
import { Dialog } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { toast } from "../../components/ui/Toast";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";

const ACTIVE: RunOut["status"][] = ["pending", "running", "paused"];

// 秒数 → 可读耗时（如 8m 49s / 45s / -）。
function formatSec(sec: number | null | undefined): string {
  if (sec == null || Number.isNaN(sec)) return "-";
  const s = Math.round(sec);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return rem ? `${h}h ${m % 60}m` : `${h}h`;
}

export default function TaskCenter() {
  const { user, isAdmin } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [keyword, setKeyword] = useState("");
  const [owner, setOwner] = useState<"mine" | "all">(isAdmin ? "all" : "mine");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [dsRun, setDsRun] = useState<RunOut | null>(null);
  const [confirmDel, setConfirmDel] = useState<{ id: string; name: string } | null>(null);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);

  const { data: kpi } = useQuery({
    queryKey: ["dashboard", "summary", since, until],
    queryFn: () =>
      dashboard.summary({
        since: since ? `${since}T00:00:00` : undefined,
        until: until ? `${until}T23:59:59` : undefined,
      }),
  });

  const { data: pageData, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["runs", "list", keyword, owner, status, page, pageSize],
    queryFn: () =>
      runs.list({
        keyword: keyword || undefined,
        owner,
        status: status || undefined,
        page,
        page_size: pageSize,
      }),
  });
  const list = pageData?.items ?? [];
  const total = pageData?.total ?? 0;

  // 操作列固定在最右：当左侧有内容被遮挡（溢出且未滚到最右）时显示左阴影，提示可横向滚动
  const checkScrolled = () => {
    const el = scrollRef.current;
    if (el) setScrolled(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  };
  const onTableScroll = checkScrolled;
  useEffect(checkScrolled, [pageData]);

  // 筛选条件或每页数量变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [keyword, owner, status, since, until, pageSize]);


  // 流程模板列表（flow_template_id → 环境名称），用于「环境」列展示
  const { data: templates } = useQuery({
    queryKey: ["flowTemplates", "list"],
    queryFn: () => flowTemplates.list(),
  });
  const envNameByTemplate = new Map((templates || []).map((t) => [t.id, t.name]));

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["runs"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const act = useMutation<RunOut | { message: string; ok: boolean }, Error, { id: string; op: "pause" | "resume" | "stop" | "delete" }>({
    mutationFn: async ({ id, op }) => {
      if (op === "pause") return runs.pause(id);
      if (op === "resume") return runs.resume(id);
      if (op === "stop") return runs.stop(id);
      return runs.remove(id);
    },
    onSuccess: (_d, v) => {
      toast("success", v.op === "delete" ? "已删除" : "操作成功");
      invalidate();
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "操作失败"),
  });

  const canOperate = (r: RunOut) => isAdmin || r.owner_id === user?.id;

  // 查看报告：直接用 run 上关联的 report_id
  const openReport = (r: RunOut) => {
    if (r.report_id) navigate(`/reports/${r.report_id}`);
    else toast("error", "该任务暂无报告（任务完成后自动生成）");
  };
  // 查看数据集：弹出数据集列表（与数据集页一致的弹窗展示）
  const openDataset = (r: RunOut) => setDsRun(r);

  const onDownload = (d: DatasetOut) => {
    datasets
      .download(d.id)
      .then(() => toast("success", "开始下载"))
      .catch((e) => toast("error", e instanceof ApiError ? e.message : "下载失败"));
  };

  return (
    <div className="space-y-6">
      {/* KPI 看板（随下方日期过滤联动） */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="总测试次数" value={formatNumber(kpi?.total_runs)} />
        <KpiCard label="总用例数" value={formatNumber(kpi?.total_cases)} />
        <KpiCard label="总通过数" value={formatNumber(kpi?.passed_cases)} tone="success" />
        <KpiCard label="总失败数" value={formatNumber(kpi?.failed_cases)} tone={kpi && kpi.failed_cases > 0 ? "error" : undefined} />
      </div>

      {/* 任务列表 */}
      <Card
        title="任务列表"
        extra={
          <Button onClick={() => navigate("/execution")}>
            <Plus size={16} /> 新建任务
          </Button>
        }
      >
        <div className="flex flex-wrap items-end gap-4 mb-4">
          <div className="min-w-[220px] flex-1 max-w-xs">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">任务名称</label>
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
              <Input
                className="pl-9"
                placeholder="搜索任务名称"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </div>
          </div>
          {isAdmin && (
            <div className="w-32">
              <label className="block text-[11px] text-[var(--color-body)] mb-1.5">发起人</label>
              <Select value={owner} onChange={(e) => setOwner(e.target.value as "mine" | "all")}>
                <option value="all">全部</option>
                <option value="mine">我的</option>
              </Select>
            </div>
          )}
          <div className="w-36">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">状态</label>
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">全部状态</option>
              <option value="pending">待执行</option>
              <option value="running">执行中</option>
              <option value="paused">已暂停</option>
              <option value="done">已完成</option>
              <option value="stopped">已停止</option>
              <option value="error">异常</option>
            </Select>
          </div>
          <div className="w-40">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">开始日期</label>
            <Input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          </div>
          <div className="w-40">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">结束日期</label>
            <Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
          </div>
          {(since || until) && (
            <Button variant="ghost" className="h-10" onClick={() => { setSince(""); setUntil(""); }}>
              清除日期
            </Button>
          )}
          <div className="ml-auto">
            <Button variant="outline" className="h-10" onClick={() => refetch()} disabled={isFetching}>
              <RefreshCw size={16} className={isFetching ? "animate-spin" : ""} /> 刷新
            </Button>
          </div>
        </div>

        {isLoading ? (
          <EmptyState title="加载中…" />
        ) : !list || list.length === 0 ? (
          <EmptyState title="暂无任务" hint="去评测执行创建第一个任务" />
        ) : (
          <>
          <div ref={scrollRef} onScroll={onTableScroll} className="overflow-x-auto">
            <table className="w-full min-w-[1280px] table-fixed text-[11px]">
              <thead>
                <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)] whitespace-nowrap">
                  <th className="!p-[5px] font-medium w-[50px] min-w-[50px] max-w-[50px]">编号</th>
                  <th className="!p-[5px] font-medium w-[80px] min-w-[80px] max-w-[80px]">任务名称</th>
                  <th className="!p-[5px] font-medium w-[80px]">类型</th>
                  <th className="!p-[5px] font-medium w-[100px]">测试人员</th>
                  <th className="!p-[5px] font-medium w-[50px] min-w-[50px] max-w-[50px]">开始时间</th>
                  <th className="!p-[5px] font-medium w-[50px] min-w-[50px] max-w-[50px]">结束时间</th>
                  <th className="!p-[5px] font-medium w-[60px] min-w-[60px] max-w-[60px]">状态</th>
                  <th className="!p-[5px] font-medium w-[60px] min-w-[60px] max-w-[60px]">执行耗时</th>
                  <th className="!p-[5px] font-medium w-[50px] min-w-[50px] max-w-[50px]">打分状态</th>
                  <th className="!p-[5px] font-medium w-[60px] min-w-[60px] max-w-[60px]">打分耗时</th>
                  <th className="!p-[5px] font-medium w-[120px]">执行/通过/失败</th>
                  <th className="!p-[5px] font-medium w-[120px]">环境</th>
                  <th className={`!p-[5px] font-medium w-[150px] sticky right-0 z-10 bg-[var(--color-surface)] ${scrolled ? "shadow-[-8px_0_8px_-8px_rgba(0,0,0,0.18)]" : ""}`}>操作</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r, i) => (
                  <tr key={r.id} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="!p-[5px] w-[50px] min-w-[50px] max-w-[50px] text-[var(--color-body)]">{i + 1}</td>
                    <td className="!p-[5px] w-[80px] min-w-[80px] max-w-[80px] truncate text-[var(--color-title)] font-medium" title={r.task_name}>{r.task_name || "-"}</td>
                    <td className="!p-[5px] w-[80px] whitespace-nowrap text-[var(--color-body)]">{r.mode === "eval_import" ? "评测结果打分" : "执行"}</td>
                    <td className="!p-[5px] w-[100px] whitespace-nowrap text-[var(--color-body)]">{r.username || "-"}</td>
                    <td className="!p-[5px] w-[50px] min-w-[50px] max-w-[50px]"><TimeCell iso={r.started_at} /></td>
                    <td className="!p-[5px] w-[50px] min-w-[50px] max-w-[50px]"><TimeCell iso={r.finished_at} /></td>
                    <td className="!p-[5px] w-[60px] min-w-[60px] max-w-[60px] whitespace-nowrap"><StatusBadge status={r.status} /></td>
                    <td className="!p-[5px] w-[60px] min-w-[60px] max-w-[60px] text-[var(--color-muted)] whitespace-nowrap">{formatSec(r.exec_sec != null && r.target_concurrency > 0 ? r.exec_sec / r.target_concurrency : r.exec_sec)}</td>
                    <td className="!p-[5px] w-[50px] min-w-[50px] max-w-[50px] whitespace-nowrap">
                      <span className={r.score_status === "scored" ? "text-[var(--color-success)]" : "text-[var(--color-muted)]"}>
                        {r.score_status === "scored" ? "已打分" : "待打分"}
                      </span>
                    </td>
                    <td className="!p-[5px] w-[60px] min-w-[60px] max-w-[60px] text-[var(--color-muted)] whitespace-nowrap">{formatSec(r.score_sec != null && r.model_concurrency > 0 ? r.score_sec / r.model_concurrency : r.score_sec)}</td>
                    <td className="!p-[5px] w-[120px] whitespace-nowrap text-[var(--color-body)]">
                      <span>{r.done_cases}</span>
                      <span className="text-[var(--color-muted)]">/</span>
                      <span className="text-[var(--color-success)]">{r.passed_cases}</span>
                      <span className="text-[var(--color-muted)]">/</span>
                      <span className="text-[var(--color-error)]">{r.failed_cases}</span>
                    </td>
                    <td className="!p-[5px] w-[120px] truncate text-[var(--color-body)]" title={envNameByTemplate.get(r.flow_template_id) || ""}>
                      {envNameByTemplate.get(r.flow_template_id) || "-"}
                    </td>
                    <td
                      className={`!p-[5px] w-[150px] sticky right-0 z-10 bg-[var(--color-surface)] ${scrolled ? "shadow-[-8px_0_8px_-8px_rgba(0,0,0,0.18)]" : ""}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-0.5">
                          <Button variant="ghost" className="h-7 !px-1.5 !gap-1" onClick={() => openDataset(r)}>
                            <Database size={14} /> 用例
                          </Button>
                          <Button variant="ghost" className="h-7 !px-1.5 !gap-1" onClick={() => navigate(`/runs/${r.id}`)}>
                            <Eye size={14} /> 结果
                          </Button>
                          <Button variant="ghost" className="h-7 !px-1.5 !gap-1" onClick={() => openReport(r)}>
                            <FileBarChart size={14} /> 报告
                          </Button>
                        </div>
                        {(ACTIVE.includes(r.status) && canOperate(r)) || isAdmin ? (
                          <div className="flex items-center gap-0.5">
                            {ACTIVE.includes(r.status) && canOperate(r) && (
                              <>
                                {r.status !== "paused" && (
                                  <Button variant="ghost" className="h-7 !px-1.5" onClick={() => act.mutate({ id: r.id, op: "pause" })}>
                                    暂停
                                  </Button>
                                )}
                                {r.status === "paused" && (
                                  <Button variant="ghost" className="h-7 !px-1.5" onClick={() => act.mutate({ id: r.id, op: "resume" })}>
                                    继续
                                  </Button>
                                )}
                                <Button variant="ghost" className="h-7 !px-1.5 text-[var(--color-error)]" onClick={() => act.mutate({ id: r.id, op: "stop" })}>
                                  停止
                                </Button>
                              </>
                            )}
                            {isAdmin && (
                              <Button
                                variant="ghost"
                                className="h-7 !px-1.5 text-[var(--color-error)]"
                                disabled={ACTIVE.includes(r.status)}
                                title={ACTIVE.includes(r.status) ? "进行中任务请先停止" : "删除任务"}
                                onClick={() => setConfirmDel({ id: r.id, name: r.task_name })}
                              >
                                删除任务
                              </Button>
                            )}
                          </div>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            size={pageSize}
            total={total}
            onChange={setPage}
            sizeOptions={PAGE_SIZE_OPTIONS}
            onSizeChange={setPageSize}
          />
          </>
        )}
      </Card>

      <DatasetDialog run={dsRun} onClose={() => setDsRun(null)} onDownload={onDownload} />
      <ConfirmDialog
        open={!!confirmDel}
        title="确认删除"
        message={`确认删除任务「${confirmDel?.name}」？`}
        onConfirm={() => {
          if (confirmDel) act.mutate({ id: confirmDel.id, op: "delete" });
          setConfirmDel(null);
        }}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  );
}

/** 数据集查看弹窗：直接定位到该任务所用数据集的详情（与数据集页详情一致 + 下载）。
 *  后端 RunOut 未返回 dataset_id 时降级为数据集列表。 */
function DatasetDialog({
  run,
  onClose,
  onDownload,
}: {
  run: RunOut | null;
  onClose: () => void;
  onDownload: (d: DatasetOut) => void;
}) {
  const open = !!run;
  const datasetId = run?.dataset_id || null;
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // 打开时重置分页
  useEffect(() => {
    if (open) setPage(1);
  }, [open, datasetId]);

  const { data: ds, isLoading } = useQuery({
    queryKey: ["datasets", "get", datasetId],
    queryFn: () => datasets.get(datasetId!),
    enabled: open && !!datasetId,
  });
  const { data: pageData, isLoading: casesLoading } = useQuery({
    queryKey: ["datasets", "cases", datasetId, page],
    queryFn: () => datasets.cases(datasetId!, { page, page_size: PAGE_SIZE }),
    enabled: open && !!datasetId,
  });

  const cases = pageData?.items ?? [];
  const total = pageData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const title = run ? (ds ? ds.name : `数据集 · ${run.task_name}`) : "数据集";

  return (
    <Dialog
      open={open}
      title={title}
      onClose={onClose}
      widthClass="max-w-5xl"
      footer={
        <>
          {ds && (
            <Button variant="outline" onClick={() => onDownload(ds)}>
              <Download size={16} /> 下载数据集
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>关闭</Button>
        </>
      }
    >
      {/* 有 dataset_id：展示该数据集详情（用例表 + 分页） */}
      {datasetId ? (
        isLoading || casesLoading ? (
          <EmptyState title="加载中…" />
        ) : ds ? (
          <div className="space-y-4">
            <div className="flex items-center gap-6 text-[11px] text-[var(--color-muted)]">
              <span>用例数：<b className="text-[var(--color-title)]">{formatNumber(ds.case_count)}</b></span>
              <span>来源：{ds.source}</span>
              <span>上传时间：{formatDateTime(ds.created_at)}</span>
            </div>
            <div className="overflow-x-auto border border-[var(--color-border)] rounded-[var(--radius-form)]">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-left text-[var(--color-muted)] bg-[var(--color-surface-alt)]">
                    {CASE_HEADERS.map((h) => (
                      <th key={h} className="!p-[5px] font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr key={c.id} className="border-t border-[var(--color-border)]">
                      <td className="py-2 px-3 whitespace-nowrap text-[var(--color-title)]">{c.case_no}</td>
                      <td className="py-2 px-3 max-w-[280px] truncate" title={c.user_input}>{c.user_input}</td>
                      <td className="py-2 px-3 max-w-[280px] truncate" title={c.expected_gt}>{c.expected_gt}</td>
                      <td className="py-2 px-3 whitespace-nowrap">{c.dimension_l1 || "-"}</td>
                      <td className="py-2 px-3 whitespace-nowrap">{c.dimension_l2 || "-"}</td>
                    </tr>
                  ))}
                  {cases.length === 0 && (
                    <tr><td colSpan={CASE_HEADERS.length} className="py-8 text-center text-[var(--color-muted)]">暂无数据</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between text-[11px] text-[var(--color-muted)]">
              <span>共 {formatNumber(total)} 条用例</span>
              <div className="flex items-center gap-2">
                <Button variant="ghost" className="h-8 px-3" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</Button>
                <span className="whitespace-nowrap">{page} / {totalPages}</span>
                <Button variant="ghost" className="h-8 px-3" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>下一页</Button>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState title="未找到该任务的数据集" hint="数据集可能已被删除" />
        )
      ) : (
        /* 无 dataset_id（后端待补字段）：降级为数据集列表 */
        <FallbackDatasetList onDownload={onDownload} />
      )}
    </Dialog>
  );
}

const CASE_HEADERS = ["用例编号", "测试输入", "预期结果", "评测一级维度", "评测二级维度"];

/** 降级：后端未返回 dataset_id 时，展示数据集列表供查看/下载 */
function FallbackDatasetList({ onDownload }: { onDownload: (d: DatasetOut) => void }) {
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const PAGE_SIZE_OPTIONS = [10, 20, 50];
  const { data: dsPage, isLoading } = useQuery({
    queryKey: ["datasets", "list", "dialog", keyword, page, pageSize],
    queryFn: () => datasets.list({ keyword: keyword || undefined, page, page_size: pageSize }),
  });
  const list = dsPage?.items ?? [];
  const total = dsPage?.total ?? 0;

  // 搜索变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [keyword]);

  return (
    <div className="space-y-4">
      <div className="relative max-w-xs">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
        <Input className="pl-9" placeholder="搜索数据集" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
      </div>
      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : list.length === 0 ? (
        <EmptyState title="暂无数据集" />
      ) : (
        <>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
              <th className="!p-[5px] font-medium">名称</th>
              <th className="!p-[5px] font-medium">用例数</th>
              <th className="!p-[5px] font-medium">上传人</th>
              <th className="!p-[5px] font-medium">上传时间</th>
              <th className="!p-[5px] font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) => (
              <tr key={d.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-hover)]">
                <td className="!p-[5px] text-[var(--color-title)] font-medium">{d.name}</td>
                <td className="!p-[5px]">{formatNumber(d.case_count)}</td>
                <td className="!p-[5px]">{d.username || "-"}</td>
                <td className="!p-[5px] text-[var(--color-muted)]">{formatDateTime(d.created_at)}</td>
                <td className="!p-[5px]">
                  <div className="flex items-center justify-end gap-1.5">
                    <Button variant="ghost" className="h-8 px-2" onClick={() => onDownload(d)}>
                      <Download size={16} /> 下载
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={page}
          size={pageSize}
          total={total}
          onChange={setPage}
          sizeOptions={PAGE_SIZE_OPTIONS}
          onSizeChange={setPageSize}
        />
        </>
      )}
    </div>
  );
}
