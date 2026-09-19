import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Pencil, Trash2, Save } from "lucide-react";
import { evaluators, metrics } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import type { MetricOut } from "../../lib/types";
import { cn } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Input, Select, Textarea, Field } from "../../components/ui/Input";
import { Stepper } from "../../components/ui/Stepper";
import { Dialog } from "../../components/ui/Dialog";
import { Pagination } from "../../components/ui/Pagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { MarkdownView } from "../../components/ui/MarkdownView";
import { toast } from "../../components/ui/Toast";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";

type Tab = "standard" | "library";

interface EditMetric {
  metric_id: string;
  name: string;
  weight: number;
}

export default function Evaluator() {
  const [tab, setTab] = useState<Tab>("standard");
  return (
    <div className="space-y-6">
      <div className="flex gap-1 border-b border-[var(--color-border)]">
        {(["standard", "library"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2.5 text-[11px] border-b-2 -mb-px cursor-pointer",
              tab === t
                ? "border-[var(--brand)] text-[var(--brand)] font-medium"
                : "border-transparent text-[var(--color-body)] hover:text-[var(--color-title)]"
            )}
          >
            {t === "standard" ? "标准评估器" : "指标库"}
          </button>
        ))}
      </div>
      {tab === "standard" ? <StandardEvaluator /> : <MetricLibrary />}
    </div>
  );
}

function StandardEvaluator() {
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const { data: std } = useQuery({ queryKey: ["evaluators", "standard"], queryFn: () => evaluators.getStandard() });
  // 候选指标（轻量 id+name）
  const { data: allMetrics } = useQuery({ queryKey: ["metrics", "options"], queryFn: () => metrics.options() });

  const [rows, setRows] = useState<EditMetric[] | null>(null);
  const [desc, setDesc] = useState<string>("");

  const save = useMutation({
    mutationFn: () =>
      evaluators.updateStandard({
        description: desc || null,
        metrics: (rows || []).map((r) => ({ metric_id: r.metric_id, weight: r.weight })),
      }),
    onSuccess: () => {
      toast("success", "已保存标准评估器");
      qc.invalidateQueries({ queryKey: ["evaluators"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "保存失败"),
  });

  // 初始化编辑行
  if (std && rows === null) {
    setRows(std.metrics.map((m) => ({ metric_id: m.metricId, name: m.name, weight: m.weight })));
    setDesc(std.description || "");
  }
  if (rows === null) return <EmptyState title="加载中…" />;

  const sum = rows.reduce((s, r) => s + r.weight, 0);
  const sumOk = Math.abs(sum - 1) <= 0.005;

  const candidates = (allMetrics || []).filter((m) => !rows.some((r) => r.metric_id === m.id));

  const setWeight = (i: number, w: number) => setRows((rs) => rs!.map((r, idx) => (idx === i ? { ...r, weight: w } : r)));
  const remove = (i: number) => setRows((rs) => rs!.filter((_, idx) => idx !== i));
  const add = (metricId: string) => {
    const m = (allMetrics || []).find((x) => x.id === metricId);
    if (!m) return;
    setRows((rs) => [...rs!, { metric_id: m.id, name: m.name, weight: 0 }]);
  };

  return (
    <Card
      title="标准评估器"
      extra={
        isAdmin && (
          <Button onClick={() => save.mutate()} disabled={!sumOk || save.isPending}>
            <Save size={16} /> 保存
          </Button>
        )
      }
    >
      {isAdmin && (
        <div className="mb-4">
          <Field label="评估器描述">
            <Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="可选" />
          </Field>
        </div>
      )}
      <div className="flex items-center justify-between mb-2 text-[11px]">
        <span className="text-[var(--color-muted)]">权重合计需等于 1</span>
        <span className={cn("font-medium", sumOk ? "text-[var(--color-success)]" : "text-[var(--color-error)]")}>
          当前合计：{sum.toFixed(2)}
        </span>
      </div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
            <th className="py-2.5 px-3 font-medium">指标</th>
            <th className="py-2.5 px-3 font-medium w-64">权重</th>
            {isAdmin && <th className="py-2.5 px-3 font-medium text-right">操作</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.metric_id} className="border-b border-[var(--color-border)] last:border-0">
              <td className="py-3 px-3 text-[var(--color-title)]">{r.name}</td>
              <td className="py-3 px-3">
                <Stepper value={r.weight} onChange={(v) => setWeight(i, v)} disabled={!isAdmin} />
              </td>
              {isAdmin && (
                <td className="py-3 px-3 text-right">
                  <button onClick={() => remove(i)} className="text-[var(--color-error)] cursor-pointer" title="移除">
                    <Trash2 size={16} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {isAdmin && candidates.length > 0 && (
        <div className="flex items-center gap-2 mt-4">
          <span className="text-[11px] text-[var(--color-muted)] whitespace-nowrap">添加指标：</span>
          <Select defaultValue="" className="w-56" onChange={(e) => e.target.value && add(e.target.value)}>
            <option value="">选择指标…</option>
            {candidates.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </Select>
        </div>
      )}
    </Card>
  );
}

function MetricLibrary() {
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const [category, setCategory] = useState("");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(10);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

  const { data: pageData, isLoading } = useQuery({
    queryKey: ["metrics", "library", category, keyword, page, size],
    queryFn: () => metrics.list({ category: category || undefined, keyword: keyword || undefined, page, page_size: size }),
  });
  const list = pageData?.items ?? [];
  const total = pageData?.total ?? 0;

  // 筛选条件或每页数量变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [category, keyword, size]);

  const [editing, setEditing] = useState<MetricOut | "new" | null>(null);
  const [confirmDel, setConfirmDel] = useState<{ id: string; name: string } | null>(null);

  const del = useMutation({
    mutationFn: (id: string) => metrics.remove(id),
    onSuccess: () => {
      toast("success", "已删除");
      qc.invalidateQueries({ queryKey: ["metrics"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "删除失败"),
  });

  return (
    <Card
      title="指标库"
      extra={
        isAdmin && (
          <Button onClick={() => setEditing("new")}>
            <Plus size={16} /> 新建指标
          </Button>
        )
      }
    >
      <div className="flex flex-wrap items-end gap-4 mb-4">
        <div className="min-w-[220px] flex-1 max-w-xs">
          <label className="block text-[11px] text-[var(--color-body)] mb-1.5">指标名称</label>
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
            <Input className="pl-9" placeholder="搜索指标" value={keyword} onChange={(e) => { setKeyword(e.target.value); setPage(1); }} />
          </div>
        </div>
        <div className="w-32">
          <label className="block text-[11px] text-[var(--color-body)] mb-1.5">类型</label>
          <Select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
            <option value="">全部类型</option>
            <option value="tech">技术</option>
            <option value="biz">业务</option>
          </Select>
        </div>
      </div>

      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : list.length === 0 ? (
        <EmptyState title="暂无指标" />
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {list.map((m) => (
              <div
                key={m.id}
                className="border border-[var(--color-border)] rounded-[var(--radius-form)] p-4 hover:shadow-[var(--shadow-card)] transition-shadow"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-[var(--color-title)] font-medium flex items-center gap-2">
                      {m.name}
                      <span className={cn("px-1.5 py-0.5 rounded text-[8px]", m.category === "tech" ? "bg-[#E8F0FE] text-[var(--intl-blue)]" : "bg-[#FDF6EC] text-[var(--color-warning)]")}>
                        {m.category === "tech" ? "技术" : "业务"}
                      </span>
                    </div>
                    {m.industry && <div className="text-[11px] text-[var(--color-muted)] mt-0.5">行业：{m.industry}</div>}
                  </div>
                  {isAdmin && (
                    <div className="flex gap-1">
                      <button onClick={() => setEditing(m)} className="text-[var(--color-muted)] hover:text-[var(--brand)] cursor-pointer" title="编辑">
                        <Pencil size={16} />
                      </button>
                      <button
                        onClick={() => setConfirmDel({ id: m.id, name: m.name })}
                        className="text-[var(--color-muted)] hover:text-[var(--color-error)] cursor-pointer"
                        title="删除"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  )}
                </div>
                {m.description && <p className="text-[11px] text-[var(--color-body)] mt-2 mb-0 line-clamp-2">{m.description}</p>}
              </div>
            ))}
          </div>
          <Pagination
            page={page}
            size={size}
            total={total}
            onChange={setPage}
            sizeOptions={PAGE_SIZE_OPTIONS}
            onSizeChange={setSize}
          />
        </>
      )}

      <MetricFormDialog open={editing !== null} initial={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={!!confirmDel}
        title="确认删除"
        message={`确认删除指标「${confirmDel?.name}」？`}
        onConfirm={() => {
          if (confirmDel) del.mutate(confirmDel.id);
          setConfirmDel(null);
        }}
        onCancel={() => setConfirmDel(null)}
      />
    </Card>
  );
}

function MetricFormDialog({
  open,
  initial,
  onClose,
}: {
  open: boolean;
  initial: MetricOut | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [category, setCategory] = useState("tech");
  const [industry, setIndustry] = useState("");
  const [description, setDescription] = useState("");
  const [skillMd, setSkillMd] = useState("");
  const [ready, setReady] = useState(false);

  // 打开时填充
  if (open && !ready) {
    setName(initial?.name || "");
    setCategory(initial?.category || "tech");
    setIndustry(initial?.industry || "");
    setDescription(initial?.description || "");
    setSkillMd(initial?.skill_md || "");
    setReady(true);
  }
  if (!open && ready) setReady(false);

  const save = useMutation({
    mutationFn: () => {
      const body = { name, category, industry: industry || null, description: description || null, skill_md: skillMd };
      return initial ? metrics.update(initial.id, body) : metrics.create(body);
    },
    onSuccess: () => {
      toast("success", "已保存");
      qc.invalidateQueries({ queryKey: ["metrics"] });
      onClose();
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "保存失败"),
  });

  return (
    <Dialog
      open={open}
      title={initial ? "编辑指标" : "新建指标"}
      onClose={onClose}
      widthClass="max-w-2xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button onClick={() => save.mutate()} disabled={!name || !skillMd || save.isPending}>保存</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="指标名称" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="类型" required>
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="tech">技术</option>
              <option value="biz">业务</option>
            </Select>
          </Field>
        </div>
        {category === "biz" && (
          <Field label="行业">
            <Input value={industry} onChange={(e) => setIndustry(e.target.value)} />
          </Field>
        )}
        <Field label="描述">
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label="评分要求（skill.md）" required hint="将作为评分 prompt 的要求，支持 Markdown">
          <Textarea value={skillMd} onChange={(e) => setSkillMd(e.target.value)} className="min-h-[160px] font-mono" />
        </Field>
        {skillMd && (
          <div className="border-t border-[var(--color-border)] pt-3">
            <div className="text-[11px] text-[var(--color-muted)] mb-2">预览</div>
            <MarkdownView source={skillMd} />
          </div>
        )}
      </div>
    </Dialog>
  );
}
