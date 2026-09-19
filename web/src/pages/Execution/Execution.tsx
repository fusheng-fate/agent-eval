import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as XLSX from "xlsx";
import { Check, ChevronDown, ChevronUp, Lock, Play, Search, ShieldCheck, Upload, X } from "lucide-react";
import { evaluators, metrics, datasets, flowTemplates, runs, configs } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import type { DatasetOut, FlowTemplateOut, SelfCheckTraceStep, EvalImportColumnMapping } from "../../lib/types";
import { cn } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Input, Select, Field } from "../../components/ui/Input";
import { Dialog } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { toast } from "../../components/ui/Toast";
import { AutoResizeTextarea } from "../../components/flow/AutoResizeTextarea";

const TABS = ["评估器选择", "数据集选择", "测试环境选择", "测试执行", "评测结果"] as const;

export default function Execution() {
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();

  const [step, setStep] = useState(0);
  const [taskName, setTaskName] = useState("");
  const [extraIds, setExtraIds] = useState<string[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [overrides, setOverrides] = useState<Record<string, unknown>>({});
  const [roundSize, setRoundSize] = useState<number>(1);
  const [createdRunId, setCreatedRunId] = useState("");
  const [importOpen, setImportOpen] = useState(false);

  // 数据集筛选（与数据集页一致：名称/上传人/日期 + 分页）
  const [dsOwner, setDsOwner] = useState<string>(isAdmin ? "all" : "mine");
  const [dsKeyword, setDsKeyword] = useState("");
  const [dsStart, setDsStart] = useState("");
  const [dsEnd, setDsEnd] = useState("");
  const [dsPage, setDsPage] = useState(1);
  const DS_PAGE_SIZE = 10;

  const { data: std } = useQuery({ queryKey: ["evaluators", "standard"], queryFn: () => evaluators.getStandard() });
  const { data: allMetrics } = useQuery({
    queryKey: ["metrics", "options"],
    queryFn: () => metrics.options(),
  });
  const { data: dsUploaders } = useQuery({
    queryKey: ["datasets", "uploaders"],
    queryFn: () => datasets.uploaders(),
  });
  const { data: dsPageData, isLoading: dsLoading } = useQuery({
    queryKey: ["datasets", "list", "exec", dsOwner, dsKeyword, dsStart, dsEnd, dsPage],
    queryFn: () =>
      datasets.list({
        ...(dsOwner === "all"
          ? { owner: "all" }
          : dsOwner === "mine"
            ? { owner: "mine" }
            : { username: dsOwner }),
        keyword: dsKeyword || undefined,
        created_start: dsStart ? `${dsStart}T00:00:00` : undefined,
        created_end: dsEnd ? `${dsEnd}T23:59:59` : undefined,
        page: dsPage,
        page_size: DS_PAGE_SIZE,
      }),
  });
  // 流程模板（分页 + 搜索）
  const [tplKeyword, setTplKeyword] = useState("");
  const [tplPage, setTplPage] = useState(1);
  const [tplSize, setTplSize] = useState(10);
  const TPL_PAGE_SIZE_OPTIONS = [10, 20, 50];
  const { data: tplPageData, isLoading: tplLoading } = useQuery({
    queryKey: ["flowTemplates", "list", tplKeyword, tplPage, tplSize],
    queryFn: () => flowTemplates.listPaged({ keyword: tplKeyword || undefined, page: tplPage, page_size: tplSize }),
  });
  const tplList: FlowTemplateOut[] = tplPageData?.items ?? [];
  const tplTotal = tplPageData?.total ?? 0;
  useEffect(() => { setTplPage(1); }, [tplKeyword, tplSize]);
  const { data: cfgList } = useQuery({ queryKey: ["configs", "list"], queryFn: () => configs.list() });

  const uploaderList = dsUploaders || [];
  const dsItems = dsPageData?.items ?? [];
  const dsTotal = dsPageData?.total ?? 0;
  const dsTotalPages = Math.max(1, Math.ceil(dsTotal / DS_PAGE_SIZE));

  // 已选数据集（跨筛选/翻页保留）
  const [dsSelName, setDsSelName] = useState("");
  useEffect(() => {
    const cur = dsItems.find((d) => d.id === datasetId);
    if (cur) setDsSelName(cur.name);
  }, [dsItems, datasetId]);

  // 模型并发来自配置中心（concurrency.model）；被测并发来自所选流程模板（target_concurrency）
  const cfgVal = (key: string): string => {
    const c = (cfgList || []).find((x) => x.config_key === key);
    if (!c) return "-";
    const v = c.config_value;
    return String(v && typeof v === "object" && "value" in (v as object) ? (v as { value: unknown }).value : v ?? "");
  };

  const standardIds = useMemo(() => new Set((std?.metrics || []).map((m) => m.metricId)), [std]);
  const extraCandidates = (allMetrics || []).filter((m) => !standardIds.has(m.id));
  // 选中的模板：优先从当前页取，翻页后不在当前页则单独查
  const inPageTpl = tplList.find((t) => t.id === templateId);
  const { data: fetchedTpl } = useQuery({
    queryKey: ["flowTemplates", "get", templateId],
    queryFn: () => flowTemplates.get(templateId),
    enabled: !!templateId && !inPageTpl,
  });
  const selectedTpl = inPageTpl || fetchedTpl || null;
  const selectedDs = dsItems.find((d) => d.id === datasetId) || null;

  // 筛选条件变化时回到第一页
  useEffect(() => {
    setDsPage(1);
  }, [dsOwner, dsKeyword, dsStart, dsEnd]);

  const editablePaths = useMemo(() => {
    if (!selectedTpl) return [];
    if (isAdmin) return selectedTpl.param_perms.map((p) => p.paramPath);
    return selectedTpl.param_perms.filter((p) => p.userEditable).map((p) => p.paramPath);
  }, [selectedTpl, isAdmin]);

  // 选择模板时，把每个可开放参数的「默认值」（= 字段在模板中的当前取值）预填进 overrides，用户可再改
  // 例外：pre_api_groups（变量组整体）不预填——变量组框留空即沿用模板原值，
  // 预填整个数组会与上方逐变量框（pre_api_groups[i].<k>）重复且易混淆。
  useEffect(() => {
    if (!selectedTpl) { setOverrides({}); return; }
    const o: Record<string, unknown> = {};
    for (const p of selectedTpl.param_perms) {
      if (p.paramPath === "pre_api_groups") continue;
      const v = getParamValue(selectedTpl.chain_json, p.paramPath);
      if (v !== undefined && v !== null) o[p.paramPath] = typeof v === "object" ? JSON.stringify(v) : String(v);
    }
    setOverrides(o);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId]);

  const ready = taskName.trim() && datasetId && templateId;
  const totalRounds = roundSize > 0 && selectedDs ? Math.ceil(selectedDs.case_count / roundSize) : null;

  const create = useMutation({
    mutationFn: () =>
      runs.create({
        task_name: taskName.trim(),
        dataset_id: datasetId,
        flow_template_id: templateId,
        extra_metric_ids: extraIds,
        overrides,
        round_size: roundSize > 0 ? roundSize : undefined,
      }),
    onSuccess: (run) => {
      toast("success", "任务已创建");
      setCreatedRunId(run.id);
      setStep(4);
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "创建失败"),
  });

  return (
    <div className={cn("space-y-6", step === 4 && "flex flex-col h-[calc(100vh-96px)]")}>
      {/* 导入评测结果打分入口（跳过调被测 Agent，直接对已有输出打分） */}
      <div className="flex justify-end">
        <Button variant="outline" onClick={() => setImportOpen(true)}>
          <Upload size={16} /> 导入评测结果打分
        </Button>
      </div>
      {/* 步骤页签 */}
      <div className="flex flex-wrap gap-1 border-b border-[var(--color-border)]">
        {TABS.map((t, i) => (
          <button
            key={t}
            onClick={() => setStep(i)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2.5 text-[11px] border-b-2 -mb-px cursor-pointer",
              step === i
                ? "border-[var(--brand)] text-[var(--brand)] font-medium"
                : "border-transparent text-[var(--color-body)] hover:text-[var(--color-title)]"
            )}
          >
            <span
              className={cn(
                "w-5 h-5 rounded-full text-[8px] flex items-center justify-center",
                step === i ? "bg-[var(--brand)] text-white" : "bg-[var(--color-surface-alt)] text-[var(--color-muted)]"
              )}
            >
              {i + 1}
            </span>
            {t}
          </button>
        ))}
      </div>

      {step === 0 && (
        <Card title="评估器选择">
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[11px] text-[var(--color-body)] font-medium">标准评估器（必选）</span>
              <StatusBadge status="done" />
            </div>
            <div className="border border-[var(--color-border)] rounded p-3 text-[11px]">
              {(std?.metrics || []).map((m) => (
                <div key={m.metricId} className="flex justify-between py-1">
                  <span className="text-[var(--color-title)]">{m.name}</span>
                  <span className="text-[var(--color-muted)]">权重 {m.weight}</span>
                </div>
              ))}
              {(!std || std.metrics.length === 0) && <span className="text-[var(--color-muted)]">暂无标准指标</span>}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--color-body)] font-medium mb-1">额外指标（可选，单独计分不计入主分，上限 5）</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {extraCandidates.map((m) => {
                const on = extraIds.includes(m.id);
                return (
                  <label
                    key={m.id}
                    className={cn(
                      "flex items-center gap-2 border rounded-[var(--radius-form)] px-3 py-2 text-[11px] cursor-pointer",
                      on ? "border-[var(--brand)] bg-[var(--color-hover)]" : "border-[var(--color-border)]"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={!on && extraIds.length >= 5}
                      onChange={(e) =>
                        setExtraIds((ids) => (e.target.checked ? [...ids, m.id] : ids.filter((x) => x !== m.id)))
                      }
                      className="accent-[var(--brand)]"
                    />
                    {m.name}
                  </label>
                );
              })}
              {extraCandidates.length === 0 && <span className="text-[11px] text-[var(--color-muted)]">无可选额外指标</span>}
            </div>
          </div>
        </Card>
      )}

      {step === 1 && (
        <Card title="数据集选择">
          {/* 筛选（与数据集页一致） */}
          <div className="flex flex-wrap items-end gap-4 mb-4">
            <div className="min-w-[220px] flex-1 max-w-xs">
              <label className="block text-[11px] text-[var(--color-body)] mb-1.5">数据集名称</label>
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
                <Input className="pl-9" placeholder="搜索数据集" value={dsKeyword} onChange={(e) => setDsKeyword(e.target.value)} />
              </div>
            </div>
            {isAdmin && (
              <div className="w-32">
                <label className="block text-[11px] text-[var(--color-body)] mb-1.5">上传人</label>
                <Select value={dsOwner} onChange={(e) => setDsOwner(e.target.value)}>
                  <option value="all">全部</option>
                  <option value="mine">我的</option>
                  {uploaderList.filter((u) => u !== user?.username).map((u) => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </Select>
              </div>
            )}
            <div className="w-40">
              <label className="block text-[11px] text-[var(--color-body)] mb-1.5">开始日期</label>
              <Input type="date" value={dsStart} onChange={(e) => setDsStart(e.target.value)} />
            </div>
            <div className="w-40">
              <label className="block text-[11px] text-[var(--color-body)] mb-1.5">结束日期</label>
              <Input type="date" value={dsEnd} onChange={(e) => setDsEnd(e.target.value)} />
            </div>
            {(dsStart || dsEnd) && (
              <Button variant="ghost" className="h-10" onClick={() => { setDsStart(""); setDsEnd(""); }}>
                清除日期
              </Button>
            )}
          </div>

          {dsLoading ? (
            <EmptyState title="加载中…" />
          ) : dsItems.length === 0 ? (
            <EmptyState title="暂无数据集" hint="请先在数据集页上传" />
          ) : (
            <>
              <div className="space-y-2">
                {dsItems.map((d: DatasetOut) => (
                  <label
                    key={d.id}
                    className={cn(
                      "flex items-center gap-3 border rounded-[var(--radius-form)] px-4 py-3 cursor-pointer",
                      datasetId === d.id ? "border-[var(--brand)] bg-[var(--color-hover)]" : "border-[var(--color-border)]"
                    )}
                  >
                    <input type="radio" name="ds" checked={datasetId === d.id} onChange={() => setDatasetId(d.id)} className="accent-[var(--brand)]" />
                    <span className="text-[var(--color-title)] font-medium flex-1">{d.name}</span>
                    <span className="text-[11px] text-[var(--color-muted)]">{d.case_count} 条用例</span>
                  </label>
                ))}
              </div>
              {/* 分页 */}
              <div className="flex items-center justify-between mt-4 text-[11px] text-[var(--color-muted)]">
                <span>共 {dsTotal} 个数据集</span>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" className="h-8 px-3" disabled={dsPage <= 1} onClick={() => setDsPage((p) => p - 1)}>上一页</Button>
                  <span className="whitespace-nowrap">{dsPage} / {dsTotalPages}</span>
                  <Button variant="ghost" className="h-8 px-3" disabled={dsPage >= dsTotalPages} onClick={() => setDsPage((p) => p + 1)}>下一页</Button>
                </div>
              </div>
            </>
          )}
          {selectedDs && (
            <div className="mt-4">
              <DsPreview id={selectedDs.id} />
            </div>
          )}
        </Card>
      )}

      {step === 2 && (
        <Card title="测试环境选择">
          <div className="relative mb-4 max-w-xs">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
            <Input className="pl-9" placeholder="搜索模板" value={tplKeyword} onChange={(e) => setTplKeyword(e.target.value)} />
          </div>
          <div className="space-y-2 mb-4">
            {tplLoading ? (
              <EmptyState title="加载中…" />
            ) : tplList.length === 0 ? (
              <EmptyState title="暂无流程模板" hint="请联系管理员在配置中心创建" />
            ) : (
              tplList.map((t: FlowTemplateOut) => (
                <label
                  key={t.id}
                  className={cn(
                    "flex items-center gap-3 border rounded-[var(--radius-form)] px-4 py-3 cursor-pointer",
                    templateId === t.id ? "border-[var(--brand)] bg-[var(--color-hover)]" : "border-[var(--color-border)]"
                  )}
                >
                  <input type="radio" name="tpl" checked={templateId === t.id} onChange={() => setTemplateId(t.id)} className="accent-[var(--brand)]" />
                  <div className="flex-1">
                    <div className="text-[var(--color-title)] font-medium">{t.name}</div>
                    {t.description && <div className="text-[11px] text-[var(--color-muted)]">{t.description}</div>}
                  </div>
                </label>
              ))
            )}
          </div>
          <Pagination
            page={tplPage}
            size={tplSize}
            total={tplTotal}
            onChange={setTplPage}
            sizeOptions={TPL_PAGE_SIZE_OPTIONS}
            onSizeChange={setTplSize}
          />

          {selectedTpl && (
            <div className="space-y-4">
              <div>
                <div className="text-[11px] text-[var(--color-body)] font-medium mb-2">
                  测试流程{selectedTpl.param_perms.length > 0 && (
                    <span className="text-[11px] text-[var(--color-muted)] ml-2">
                      （{isAdmin ? "管理员可编辑全部开放字段" : "普通用户可编辑开放字段"}）
                    </span>
                  )}
                </div>
                <ChainView
                  tpl={selectedTpl}
                  editablePaths={editablePaths}
                  overrides={overrides}
                  onOverride={(path, v) => setOverrides((o) => ({ ...o, [path]: v }))}
                />
              </div>
            </div>
          )}
        </Card>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <SelfCheck datasetId={datasetId} templateId={templateId} overrides={overrides} />
          <Card title="测试执行">
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="任务名称" required>
                <Input value={taskName} onChange={(e) => setTaskName(e.target.value)} placeholder="给任务起个名字" />
              </Field>
              <Field label="轮次大小（每组用例数）">
                <Input
                  type="number"
                  min={1}
                  value={roundSize || ""}
                  onChange={(e) => setRoundSize(Math.max(0, parseInt(e.target.value) || 0))}
                  placeholder="如 5（留空=不分组）"
                />
              </Field>
            </div>
            {roundSize > 1 && selectedDs && (
              <div className="text-[11px] text-[var(--color-body)]">
                预计 <span className="font-medium">{totalRounds}</span> 轮 × {roundSize} 用例
              </div>
            )}
            {roundSize === 1 && (
              <div className="text-[11px] text-[var(--color-muted)]">轮次大小=1 等同于不分组（无串行依赖；前置 API 仍生效，变量组按用例顺序循环分配）</div>
            )}
            <div className="grid grid-cols-2 gap-4 text-[11px]">
              <Info label="标准评估器" value={`${std?.metrics.length || 0} 项指标`} />
              <Info label="额外指标" value={`${extraIds.length} 项`} />
              <Info label="数据集" value={selectedDs?.name || dsSelName || "-"} />
              <Info label="流程模板" value={selectedTpl?.name || "-"} />
            </div>
            <div className="grid grid-cols-2 gap-4 text-[11px]">
              <Info label="模型并发" value={cfgVal("concurrency.model")} />
              <Info label="被测并发" value={selectedTpl ? String(selectedTpl.target_concurrency) : "-"} />
            </div>
            {!ready && <div className="text-[11px] text-[var(--color-warning)]">请先完成：任务名称、数据集、流程模板</div>}
          </div>
          </Card>
        </div>
      )}

      {step === 4 && (
        <Card
          title="评测结果"
          className="flex-1 min-h-0 flex flex-col"
          bodyClassName={createdRunId ? "flex-1 min-h-0 flex flex-col space-y-4" : undefined}
        >
          {createdRunId ? (
            <>
              <div className="flex items-center justify-between shrink-0">
                <span className="text-[11px] text-[var(--color-body)]">任务已创建，正在执行</span>
                <Button onClick={() => navigate(`/runs/${createdRunId}`)}>
                  <Play size={16} /> 查看任务详情
                </Button>
              </div>
              <RunLogTerminal runId={createdRunId} />
            </>
          ) : (
            <EmptyState title="尚未创建任务" hint="完成前面步骤后创建" />
          )}
        </Card>
      )}

      {/* 底部操作 */}
      <div className="flex justify-end gap-3">
        {step > 0 && (
          <Button variant="outline" onClick={() => setStep((s) => s - 1)}>上一步</Button>
        )}
        {step < 3 && (
          <Button variant="outline" onClick={() => setStep((s) => s + 1)}>下一步</Button>
        )}
        {step === 3 && (
          <Button onClick={() => create.mutate()} disabled={!ready || create.isPending}>
            <Play size={16} /> 创建任务并开始执行
          </Button>
        )}
      </div>
      {/* 提示当前用户 */}
      <div className="text-[11px] text-[var(--color-muted)]">当前用户：{user?.display_name || user?.username}（{isAdmin ? "管理员" : "普通用户"}）</div>

      <ImportEvalDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        stdMetricIds={standardIds}
        allMetrics={allMetrics || []}
      />
    </div>
  );
}

// 导入评测结果打分弹窗：上传导出 Excel → 列映射（默认按导出格式预填）→ 预览 → 建任务异步打分
const IMPORT_REQUIRED: Array<{ key: keyof EvalImportColumnMapping; label: string }> = [
  { key: "case_no", label: "用例编号" },
  { key: "user_input", label: "测试输入" },
  { key: "expected_gt", label: "预期结果" },
  { key: "agent_output", label: "执行结果" },
];
const IMPORT_OPTIONAL: Array<{ key: keyof EvalImportColumnMapping; label: string }> = [
  { key: "dimension_l1", label: "评测一级维度" },
  { key: "dimension_l2", label: "评测二级维度" },
];
// 平台导出 eval 格式的默认表头（用于自动预填列映射）
const IMPORT_DEFAULT_HEADERS: Record<string, string> = {
  case_no: "用例编号", user_input: "测试输入", expected_gt: "预期结果",
  agent_output: "执行结果", dimension_l1: "评测一级维度", dimension_l2: "评测二级维度",
};

function ImportEvalDialog({
  open, onClose, stdMetricIds, allMetrics,
}: {
  open: boolean;
  onClose: () => void;
  stdMetricIds: Set<string>;
  allMetrics: Array<{ id: string; name: string }>;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [taskName, setTaskName] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<unknown[][]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [extraIds, setExtraIds] = useState<string[]>([]);

  const reset = () => {
    setFile(null); setTaskName(""); setHeaders([]); setRows([]); setMapping({}); setExtraIds([]);
    if (fileRef.current) fileRef.current.value = "";
  };

  const onFile = async (f: File) => {
    setFile(f);
    if (!taskName) setTaskName(f.name.replace(/\.xlsx$/i, ""));
    try {
      const buf = await f.arrayBuffer();
      const wb = XLSX.read(buf);
      const ws = wb.Sheets[wb.SheetNames[0]];
      const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, defval: "" });
      const head = (aoa[0] || []).map(String);
      setHeaders(head);
      setRows(aoa.slice(1, 6));
      // 默认按导出格式表头自动预填列映射（表头匹配上才预填，否则留空让用户选）
      const m: Record<string, string> = {};
      for (const [key, defaultHeader] of Object.entries(IMPORT_DEFAULT_HEADERS)) {
        if (head.includes(defaultHeader)) m[key] = defaultHeader;
      }
      setMapping(m);
    } catch {
      toast("error", "读取 Excel 失败");
    }
  };

  const requiredOk = IMPORT_REQUIRED.every(({ key }) => mapping[key]);
  const extraCandidates = allMetrics.filter((m) => !stdMetricIds.has(m.id));

  const submit = useMutation({
    mutationFn: () =>
      runs.import(file!, taskName.trim(), {
        case_no: mapping.case_no,
        user_input: mapping.user_input,
        expected_gt: mapping.expected_gt,
        agent_output: mapping.agent_output,
        dimension_l1: mapping.dimension_l1 || null,
        dimension_l2: mapping.dimension_l2 || null,
      } as EvalImportColumnMapping, extraIds),
    onSuccess: (run) => {
      toast("success", "打分任务已创建");
      qc.invalidateQueries({ queryKey: ["runs"] });
      reset();
      onClose();
      navigate(`/runs/${run.id}`);
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "导入失败"),
  });

  return (
    <Dialog
      open={open}
      title="导入评测结果打分"
      onClose={() => { reset(); onClose(); }}
      widthClass="max-w-3xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => { reset(); onClose(); }}>取消</Button>
          <Button onClick={() => submit.mutate()} disabled={!file || !taskName.trim() || !requiredOk || submit.isPending}>
            {submit.isPending ? "导入中…" : "导入并创建打分任务"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-[11px] text-[var(--color-body)]">
          上传"评测结束导出的结果 Excel"，跳过调被测 Agent，直接按标准评估器打分。
          导入即创建任务，后续查看结果 / 报告 / 导出与常规任务一致。
        </p>
        <div>
          <div className="text-[11px] text-[var(--color-body)] mb-1.5">选择 .xlsx 文件</div>
          {file ? (
            <div className="flex items-center gap-3 h-12 px-4 rounded-[var(--radius-form)] border border-[var(--color-border)] bg-[var(--color-surface-alt)]">
              <Upload size={20} className="text-[var(--brand)] shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-[var(--color-title)] truncate">{file.name}</div>
                <div className="text-[11px] text-[var(--color-muted)]">{(file.size / 1024).toFixed(1)} KB</div>
              </div>
              <button onClick={reset} className="text-[var(--color-muted)] hover:text-[var(--color-error)] cursor-pointer shrink-0" title="移除文件">
                <X size={16} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => fileRef.current?.click()}
              className="w-full h-24 rounded-[var(--radius-form)] border-2 border-dashed border-[var(--input-border)] bg-[var(--color-surface-alt)] hover:border-[var(--brand)] hover:bg-[var(--color-hover)] transition-colors cursor-pointer flex flex-col items-center justify-center gap-1.5"
            >
              <Upload size={24} className="text-[var(--color-muted)]" />
              <span className="text-[11px] text-[var(--color-body)]">点击选择 .xlsx 文件</span>
              <span className="text-[11px] text-[var(--color-muted)]">仅支持 .xlsx 格式</span>
            </button>
          )}
          <input ref={fileRef} type="file" accept=".xlsx" className="hidden"
            onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
        </div>
        <Field label="任务名称" required>
          <Input value={taskName} onChange={(e) => setTaskName(e.target.value)} />
        </Field>

        {headers.length > 0 && (
          <>
            <div>
              <div className="text-[11px] text-[var(--color-body)] mb-2">列映射（必填项必须映射，已按导出格式自动预填）</div>
              <div className="grid grid-cols-2 gap-3">
                {[...IMPORT_REQUIRED, ...IMPORT_OPTIONAL].map(({ key, label }) => (
                  <Field key={key} label={label} required={IMPORT_REQUIRED.some((r) => r.key === key)}>
                    <Select value={mapping[key] || ""} onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))}>
                      <option value="">{IMPORT_REQUIRED.some((r) => r.key === key) ? "请选择列" : "（不映射）"}</option>
                      {headers.map((h) => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </Select>
                  </Field>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[11px] text-[var(--color-body)] mb-2">前 {rows.length} 行预览</div>
              <div className="overflow-x-auto border border-[var(--color-border)] rounded">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-left text-[var(--color-muted)] bg-[var(--color-surface-alt)]">
                      {headers.map((h) => (
                        <th key={h} className="py-2 px-3 font-medium whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-t border-[var(--color-border)]">
                        {headers.map((_, j) => (
                          <td key={j} className="py-1.5 px-3 whitespace-nowrap max-w-[200px] truncate">{String(r[j] ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        <div>
          <div className="text-[11px] text-[var(--color-body)] font-medium mb-2">额外指标（可选，单独计分不计入主分，上限 5）</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {extraCandidates.map((m) => {
              const on = extraIds.includes(m.id);
              return (
                <label key={m.id}
                  className={cn(
                    "flex items-center gap-2 border rounded-[var(--radius-form)] px-3 py-2 text-[11px] cursor-pointer",
                    on ? "border-[var(--brand)] bg-[var(--color-hover)]" : "border-[var(--color-border)]"
                  )}>
                  <input type="checkbox" checked={on} disabled={!on && extraIds.length >= 5}
                    onChange={(e) => setExtraIds((ids) => (e.target.checked ? [...ids, m.id] : ids.filter((x) => x !== m.id)))}
                    className="accent-[var(--brand)]" />
                  {m.name}
                </label>
              );
            })}
            {extraCandidates.length === 0 && <span className="text-[11px] text-[var(--color-muted)]">无可选额外指标</span>}
          </div>
        </div>
      </div>
    </Dialog>
  );
}

// 按 paramPath 读取 chain_json 中字段的当前取值（即模板里的「默认值」）
// paramPath 形态：vars.<名> / apis[i].<field>[.sub] / steps[i].inputs.<key>
//   pre_api.<field>[.sub] / pre_api_groups[i].<k> / pre_api_groups.<k>（新增组）
function getParamValue(cj: Record<string, any>, path: string): unknown {
  if (path === "pre_api_groups") return cj.pre_api_groups;
  const am = path.match(/^(\w+)\[(\d+)\]\.(.+)$/);
  if (am) {
    const arr = cj[am[1]] || [];
    return arr[Number(am[2])]?.[am[3]];
  }
  const parts = path.split(".");
  if (parts[0] === "vars") return cj.variables?.[parts[1]];
  if (parts[0] === "pre_api") {
    let cur: any = cj.pre_api;
    for (let i = 1; i < parts.length; i++) cur = cur?.[parts[i]];
    return cur;
  }
  if (parts[0] === "apis" || parts[0] === "steps") {
    const arr = cj[parts[0]] || [];
    let cur: any = arr[Number(parts[1])];
    for (let i = 2; i < parts.length; i++) cur = cur?.[parts[i]];
    return cur;
  }
  return undefined;
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-[var(--color-border)] py-2">
      <span className="text-[var(--color-muted)]">{label}</span>
      <span className="text-[var(--color-title)]">{value}</span>
    </div>
  );
}

function DsPreview({ id }: { id: string }) {
  const { data } = useQuery({ queryKey: ["datasets", "preview", id], queryFn: () => datasets.preview(id) });
  if (!data) return null;
  return (
    <div className="border border-[var(--color-border)] rounded overflow-x-auto">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-[var(--color-muted)] bg-[var(--color-surface-alt)]">
            {data.headers.map((h) => <th key={h} className="py-1.5 px-3 font-medium whitespace-nowrap">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i} className="border-t border-[var(--color-border)]">
              {data.headers.map((_, j) => (
                <td key={j} className="py-1.5 px-3 whitespace-nowrap max-w-[200px] truncate">{String(r[j] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 把 paramPath 解析成 { group, idx, field }，group ∈ apis/steps/vars/pre_api/pre_api_groups
// 形如 apis[0].url / apis[1].headers.Authorization / steps[0].inputs.user_id / vars.用户名
//   / pre_api.url / pre_api.headers.X / pre_api_groups[0].phone / pre_api_groups.<k>（新增组）
function parseParamPath(path: string): { group: string; idx: number; field: string } {
  if (path === "pre_api_groups") return { group: "pre_api_groups", idx: -1, field: "__new__" };
  const m = path.match(/^(\w+)\[(\d+)\]\.(.+)$/);
  if (m) return { group: m[1], idx: Number(m[2]), field: m[3] };
  const parts = path.split(".");
  return { group: parts[0], idx: -1, field: parts.slice(1).join(".") };
}

function ChainView({
  tpl,
  editablePaths,
  overrides,
  onOverride,
}: {
  tpl: FlowTemplateOut;
  editablePaths: string[];
  overrides: Record<string, unknown>;
  onOverride: (path: string, v: string) => void;
}) {
  const cj = tpl.chain_json || { apis: [], steps: [] };
  const hasPerms = (tpl.param_perms || []).length > 0;

  // 某 API（idx）开放的可编辑参数
  const apiPerms = (idx: number) =>
    (tpl.param_perms || []).filter((p) => {
      const r = parseParamPath(p.paramPath);
      return r.group === "apis" && r.idx === idx;
    });
  const stepPerms = (idx: number) =>
    (tpl.param_perms || []).filter((p) => {
      const r = parseParamPath(p.paramPath);
      return r.group === "steps" && r.idx === idx;
    });
  const varPerms = (tpl.param_perms || []).filter((p) => parseParamPath(p.paramPath).group === "vars");
  const preApiPerms = (tpl.param_perms || []).filter((p) => {
    const r = parseParamPath(p.paramPath);
    return r.group === "pre_api" || (r.group === "pre_api_groups" && r.field !== "__new__");
  });
  // 「变量组」整体开放（paramPath === "pre_api_groups"）：展示全部变量组供修改 + 新增组入口
  const groupsOpen = (tpl.param_perms || []).some((p) => p.paramPath === "pre_api_groups");

  const renderField = (p: { paramPath: string }, label: string) => {
    const editable = editablePaths.includes(p.paramPath);
    const dv = getParamValue(cj, p.paramPath);
    const defaultStr = dv === undefined || dv === null ? "" : typeof dv === "object" ? JSON.stringify(dv) : String(dv);
    return (
      <div key={p.paramPath} className="relative">
        <div className="mb-1 text-[11px] text-[var(--color-muted)] font-mono">{label}</div>
        <Input
          disabled={!editable}
          value={String(overrides[p.paramPath] ?? "")}
          placeholder={editable ? (defaultStr ? `默认：${defaultStr}` : "输入参数值") : "不可编辑"}
          onChange={(e) => onOverride(p.paramPath, e.target.value)}
        />
        {!editable && <Lock size={14} className="absolute right-3 top-[38px] -translate-y-1/2 text-[var(--color-muted)]" />}
      </div>
    );
  };

  return (
    <div className="space-y-3 text-[11px]">
      {cj.variables && Object.keys(cj.variables).length > 0 && (
        <div>
          <div className="text-[var(--color-muted)] text-[11px] mb-1">全局变量</div>
          {varPerms.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {varPerms.map((p) => renderField(p, parseParamPath(p.paramPath).field))}
            </div>
          ) : (
            <pre className="bg-[var(--color-surface-alt)] rounded p-2 text-[11px] overflow-x-auto">{JSON.stringify(cj.variables, null, 2)}</pre>
          )}
        </div>
      )}
      {cj.pre_api && (
        <div>
          <div className="text-[var(--color-muted)] text-[11px] mb-1">
            前置 API{cj.pre_api.enabled ? "" : "（未启用）"}
            {cj.pre_api.url ? ` · ${cj.pre_api.method || "POST"} ${cj.pre_api.url}` : ""}
          </div>
          {preApiPerms.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-2">
              {preApiPerms.map((p) => renderField(p, parseParamPath(p.paramPath).field))}
            </div>
          )}
          {(() => {
            const groups = cj.pre_api_groups || [];
            if (!groupsOpen && groups.length === 0) return null;
            const groupsEditable = editablePaths.includes("pre_api_groups");
            // 以模板当前变量组为起点（应用已改的逐变量 override），用户可直接改 key / 加新组
            const base = groups.map((g, i) => {
              const ng: Record<string, string> = {};
              for (const k of Object.keys(g || {})) ng[k] = String(overrides[`pre_api_groups[${i}].${k}`] ?? g[k] ?? "");
              return ng;
            });
            const defaultJson = JSON.stringify(base, null, 2);
            const text = String(overrides["pre_api_groups"] ?? defaultJson);
            return (
            <div className="space-y-1.5">
              <div className="text-[var(--color-muted)] text-[10px]">
                变量组（循环分配给各轮次，共 {groups.length} 组）
                {groupsEditable && " · 可编辑：改 key / 值、增删组"}
              </div>
              {groupsEditable ? (
                <div>
                  <AutoResizeTextarea
                    value={text}
                    onChange={(e) => onOverride("pre_api_groups", e.target.value)}
                    placeholder='[{"phone": "13800000002", "device_id": "DEV002"}]'
                    className="w-full rounded-[var(--radius-form)] border border-[var(--input-border)] bg-white px-2 py-1.5 font-mono text-[11px] text-[var(--color-title)] placeholder:text-[var(--color-placeholder)] focus:outline-none focus:border-[var(--border-focus)]"
                  />
                  <div className="mt-1 text-[10px] text-[var(--color-muted)]">
                    JSON 数组，每个元素为一组（{"{"}变量名: 值{"}"}）。保存时整体替换变量组。
                  </div>
                </div>
              ) : (
                groups.map((g: Record<string, string>, i: number) => (
                  <div key={i} className="border border-[var(--color-border)] rounded px-2.5 py-1.5">
                    <div className="text-[10px] text-[var(--color-title)] mb-1">组 {i + 1}</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {Object.keys(g || {}).map((k) => (
                        <div key={k}>
                          <div className="mb-1 text-[11px] text-[var(--color-muted)] font-mono">{k}</div>
                          <div className="text-[11px] text-[var(--color-body)] truncate">{String(g[k] ?? "")}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
            );
          })()}
        </div>
      )}
      <div>
        <div className="text-[var(--color-muted)] text-[11px] mb-1">API 定义（{cj.apis?.length || 0}）</div>
        <div className="space-y-1">
          {(cj.apis || []).map((a, i) => {
            const perms = hasPerms ? apiPerms(i) : [];
            return (
              <div key={a.id} className="border border-[var(--color-border)] rounded px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="px-1.5 py-0.5 rounded bg-[#E8F0FE] text-[var(--intl-blue)] text-[8px] font-medium">{a.method}</span>
                  <span className="text-[var(--color-title)] font-mono text-[11px] flex-1 truncate">{a.url}</span>
                  <span className="text-[var(--color-muted)] text-[11px]">{a.id}</span>
                </div>
                {perms.length > 0 && (
                  <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                    {perms.map((p) => renderField(p, parseParamPath(p.paramPath).field))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div>
        <div className="text-[var(--color-muted)] text-[11px] mb-1">步骤（{cj.steps?.length || 0}）</div>
        <ol className="list-decimal pl-5 space-y-1">
          {(cj.steps || []).map((s, i) => {
            const perms = hasPerms ? stepPerms(i) : [];
            return (
              <li key={i} className="text-[var(--color-body)]">
                调用 <span className="font-mono text-[11px]">{s.api_id}</span>
                {perms.length > 0 && (
                  <div className="mt-1.5 ml-5 grid grid-cols-1 md:grid-cols-2 gap-3">
                    {perms.map((p) => renderField(p, parseParamPath(p.paramPath).field))}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>
      {cj.final_extract !== undefined && cj.final_extract !== "" && (
        <div>
          <div className="text-[var(--color-muted)] text-[11px] mb-1">最终输出提取（final_extract）</div>
          {typeof cj.final_extract === "string" ? (
            <div className="text-[11px] text-[var(--color-body)]">
              最后一步 · <span className="font-mono">{cj.final_extract}</span>
            </div>
          ) : (
            <div className="space-y-1">
              {Object.entries(cj.final_extract).map(([name, f]) => (
                <div key={name} className="text-[11px] text-[var(--color-body)] flex items-center gap-2">
                  <span className="font-mono text-[var(--color-title)]">{name}</span>
                  <span className="text-[var(--color-muted)]">
                    步骤{((f as { step?: number }).step ?? (cj.steps?.length || 1) - 1) + 1} ·{" "}
                    <span className="font-mono">{(f as { path: string }).path}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SelfCheck({ datasetId, templateId, overrides }: { datasetId: string; templateId: string; overrides: Record<string, unknown> }) {
  const [open, setOpen] = useState(false); // 默认收起，不强制自检
  const [exec, setExec] = useState<"idle" | "ok" | "fail">("idle");
  const [evalRes, setEvalRes] = useState<"idle" | "ok" | "fail">("idle");
  const [execMsg, setExecMsg] = useState("");
  const [evalMsg, setEvalMsg] = useState("");
  const [execTrace, setExecTrace] = useState<SelfCheckTraceStep[]>([]);

  const runExec = useMutation({
    mutationFn: () => runs.selfcheckExec({ task_name: "selfcheck", dataset_id: datasetId, flow_template_id: templateId, overrides }),
    // 后端失败也返回 HTTP 200（data.ok=false），据此判成败而非依赖抛错
    onSuccess: (r) => {
      setExec(r.ok ? "ok" : "fail");
      setExecMsg(r.message);
      setExecTrace(r.trace || []);
    },
    onError: (e) => { setExec("fail"); setExecMsg(e instanceof ApiError ? e.message : "失败"); setExecTrace([]); },
  });
  const runEval = useMutation({
    mutationFn: () => runs.selfcheckEval(),
    onSuccess: (r) => { setEvalRes("ok"); setEvalMsg(r.message); },
    onError: (e) => { setEvalRes("fail"); setEvalMsg(e instanceof ApiError ? e.message : "失败"); },
  });

  return (
    <div className="border border-[var(--color-border)] rounded-[var(--radius-card)] bg-[var(--color-surface)]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left cursor-pointer"
      >
        <ShieldCheck size={16} className="text-[var(--color-muted)] shrink-0" />
        <span className="text-[11px] font-medium text-[var(--color-title)] flex-1">自检（可选，不影响执行）</span>
        {open ? <ChevronUp size={16} className="text-[var(--color-muted)]" /> : <ChevronDown size={16} className="text-[var(--color-muted)]" />}
      </button>
      {open && (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 pt-0">
      <Card title="执行自检">
        <p className="text-[11px] text-[var(--color-body)] mb-4">取数据集第一个用例跑流程模板，验证被测 Agent 连通性。</p>
        <div className="flex items-center gap-3">
          <Button onClick={() => runExec.mutate()} disabled={!datasetId || !templateId || runExec.isPending}>
            <ShieldCheck size={16} /> 执行自检
          </Button>
          {exec !== "idle" && <StatusBadge status={exec === "ok" ? "passed" : "failed"} />}
        </div>
        {execMsg && (
          <div className="mt-3 text-[11px] flex items-start gap-2">
            {exec === "ok" ? <Check size={16} className="text-[var(--color-success)] mt-0.5 shrink-0" /> : <X size={16} className="text-[var(--color-error)] mt-0.5 shrink-0" />}
            <span className={exec === "ok" ? "text-[var(--color-body)]" : "text-[var(--color-error)]"}>{execMsg}</span>
          </div>
        )}
        {execTrace.length > 0 && <TraceView trace={execTrace} failed={exec === "fail"} />}
      </Card>
      <Card title="评测自检">
        <p className="text-[11px] text-[var(--color-body)] mb-4">验证 LLM 评测接口是否可用。</p>
        <div className="flex items-center gap-3">
          <Button onClick={() => runEval.mutate()} disabled={runEval.isPending}>
            <ShieldCheck size={16} /> 评测自检
          </Button>
          {evalRes !== "idle" && <StatusBadge status={evalRes === "ok" ? "passed" : "failed"} />}
        </div>
        {evalMsg && (
          <div className="mt-3 text-[11px] flex items-start gap-2">
            {evalRes === "ok" ? <Check size={16} className="text-[var(--color-success)] mt-0.5 shrink-0" /> : <X size={16} className="text-[var(--color-error)] mt-0.5 shrink-0" />}
            <span className={evalRes === "ok" ? "text-[var(--color-body)]" : "text-[var(--color-error)]"}>{evalMsg}</span>
          </div>
        )}
      </Card>
    </div>
      )}
    </div>
  );
}

// 自检过程轨迹：逐步展示请求/响应，失败步骤高亮，便于定位是哪一步、什么请求出的问题
function TraceView({ trace, failed }: { trace: SelfCheckTraceStep[]; failed: boolean }) {
  const [open, setOpen] = useState(failed);
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] text-[var(--link)] inline-flex items-center gap-1 cursor-pointer"
      >
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        {open ? "收起自检过程" : `查看自检过程（${trace.length} 步）`}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
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

// terminal 风格日志面板：自动轮询，按时间正序展示
function RunLogTerminal({ runId }: { runId: string }) {
  const { data: logs } = useQuery({
    queryKey: ["runs", runId, "logs"],
    queryFn: () => runs.logs(runId),
    refetchInterval: 3000, // 每 3s 轮询
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const logCount = logs?.length ?? 0;
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
    <div className="flex-1 min-h-0 flex flex-col rounded overflow-hidden border border-[var(--color-border)]">
      {/* terminal 标题栏 */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#1E1E1E] shrink-0">
        <span className="w-3 h-3 rounded-full bg-[#FF5F57]" />
        <span className="w-3 h-3 rounded-full bg-[#FEBC2E]" />
        <span className="w-3 h-3 rounded-full bg-[#28C840]" />
        <span className="ml-2 text-[11px] text-[#8B8B8B] font-mono">task logs</span>
      </div>
      {/* 日志区域：自适应撑满剩余高度 */}
      <div
        ref={containerRef}
        className="flex-1 min-h-0 bg-[#1E1E1E] p-3 overflow-y-auto font-mono text-[11px] leading-relaxed"
      >
        {logCount === 0 ? (
          <div className="text-[#6B6B6B]">等待日志输出…</div>
        ) : (
          logs!.map((l) => {
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
