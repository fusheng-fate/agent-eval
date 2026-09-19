import { useEffect, useRef, useState } from "react";
import * as XLSX from "xlsx";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, Search, Eye, Trash2, FileSpreadsheet, X, Download, Pencil } from "lucide-react";
import { datasets } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import type { ColumnMapping } from "../../lib/types";
import { formatNumber, formatDateTime } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Input, Select, Field } from "../../components/ui/Input";
import { Dialog } from "../../components/ui/Dialog";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { toast } from "../../components/ui/Toast";

const REQUIRED: Array<{ key: keyof ColumnMapping; label: string }> = [
  { key: "case_no", label: "用例编号" },
  { key: "user_input", label: "测试输入" },
  { key: "expected_gt", label: "预期结果" },
];
const OPTIONAL: Array<{ key: keyof ColumnMapping; label: string }> = [
  { key: "dimension_l1", label: "评测一级维度" },
  { key: "dimension_l2", label: "评测二级维度" },
];

export default function Datasets() {
  const { user, isAdmin } = useAuth();
  const qc = useQueryClient();
  // 上传人筛选：all=全部，mine=我的，其余为具体用户名（后端按 username 精确过滤）
  const [owner, setOwner] = useState<string>(isAdmin ? "all" : "mine");
  const [keyword, setKeyword] = useState("");
  const [createdStart, setCreatedStart] = useState("");
  const [createdEnd, setCreatedEnd] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmDel, setConfirmDel] = useState<{ type: "single"; id: string; name: string } | { type: "batch"; ids: string[] } | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

  // 上传人候选（去重列表）
  const { data: uploaderData } = useQuery({
    queryKey: ["datasets", "uploaders"],
    queryFn: () => datasets.uploaders(),
    enabled: isAdmin,
  });
  const uploaders = uploaderData || [];

  const { data: dsPage, isLoading } = useQuery({
    queryKey: ["datasets", "list", owner, keyword, createdStart, createdEnd, page, pageSize],
    queryFn: () =>
      datasets.list({
        ...(owner === "all"
          ? { owner: "all" }
          : owner === "mine"
            ? { owner: "mine" }
            : { username: owner }),
        keyword: keyword || undefined,
        // 后端按字符串比较 created_at，结束日期补当天末尾才包含当日
        created_start: createdStart ? `${createdStart}T00:00:00` : undefined,
        created_end: createdEnd ? `${createdEnd}T23:59:59` : undefined,
        page,
        page_size: pageSize,
      }),
  });
  const list = dsPage?.items ?? [];
  const total = dsPage?.total ?? 0;

  // 筛选条件或每页数量变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [owner, keyword, createdStart, createdEnd, pageSize]);

  const del = useMutation({
    mutationFn: (id: string) => datasets.remove(id),
    onSuccess: () => {
      toast("success", "已删除");
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "删除失败"),
  });

  // 批量删除（仅管理员，后端 POST /datasets/batch-delete）
  const batchDel = useMutation({
    mutationFn: (ids: string[]) => datasets.batchDelete(ids),
    onSuccess: (d) => {
      toast("success", `已删除 ${d.deleted} 个数据集`);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "批量删除失败"),
  });

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const canDelete = (ownerId: string) => isAdmin || ownerId === user?.id;

  // 改名：后端接口待提供，先乐观更新，接口就绪后联调（失败回滚）。
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => datasets.rename(id, name),
    onMutate: async ({ id, name }) => {
      await qc.cancelQueries({ queryKey: ["datasets"] });
      const prev = qc.getQueryData<unknown[]>(["datasets", "list", owner, keyword]);
      qc.setQueryData(["datasets", "list", owner, keyword], (old: unknown[]) =>
        (old as unknown[]).map((d) => (d as { id: string }).id === id ? { ...(d as object), name } : d)
      );
      return { prev };
    },
    onError: (e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["datasets", "list", owner, keyword], ctx.prev);
      toast("error", e instanceof ApiError ? e.message : "改名失败");
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
    onSuccess: () => toast("success", "已改名"),
  });

  const onDownload = (d: { id: string; name: string }) => {
    datasets
      .download(d.id)
      .then(() => toast("success", "开始下载"))
      .catch((e) => toast("error", e instanceof ApiError ? `下载接口未就绪：${e.message}` : "下载失败"));
  };

  return (
    <div className="space-y-6">
      <Card
        title="数据集"
        extra={
          <Button onClick={() => setUploadOpen(true)}>
            <Upload size={16} /> 上传数据集
          </Button>
        }
      >
        <div className="flex flex-wrap items-end gap-4 mb-4">
          <div className="min-w-[220px] flex-1 max-w-xs">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">数据集名称</label>
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
              <Input className="pl-9" placeholder="搜索数据集" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            </div>
          </div>
          {isAdmin && (
            <div className="w-32">
              <label className="block text-[11px] text-[var(--color-body)] mb-1.5">上传人</label>
              <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
                <option value="all">全部</option>
                <option value="mine">我的</option>
                {uploaders.filter((u) => u !== user?.username).map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </Select>
            </div>
          )}
          <div className="w-40">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">开始日期</label>
            <Input type="date" value={createdStart} onChange={(e) => setCreatedStart(e.target.value)} />
          </div>
          <div className="w-40">
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">结束日期</label>
            <Input type="date" value={createdEnd} onChange={(e) => setCreatedEnd(e.target.value)} />
          </div>
          {(createdStart || createdEnd) && (
            <Button variant="ghost" className="h-10" onClick={() => { setCreatedStart(""); setCreatedEnd(""); }}>
              清除日期
            </Button>
          )}
        </div>

        {isLoading ? (
          <EmptyState title="加载中…" />
        ) : !list || list.length === 0 ? (
          <EmptyState title="暂无数据集" hint="上传一个 Excel 数据集开始" />
        ) : (
          <>
            {isAdmin && selected.size > 0 && (
              <div className="flex items-center gap-3 mb-3 px-3 py-2 rounded-[var(--radius-form)] bg-[var(--color-surface-alt)]">
                <span className="text-[11px] text-[var(--color-body)]">已选 {selected.size} 项</span>
                <Button
                  variant="ghost"
                  className="h-8 px-2 text-[var(--color-error)]"
                  disabled={batchDel.isPending}
                  onClick={() => setConfirmDel({ type: "batch", ids: Array.from(selected) })}
                >
                  <Trash2 size={16} /> {batchDel.isPending ? "删除中…" : "批量删除"}
                </Button>
                <Button variant="ghost" className="h-8 px-2" onClick={() => setSelected(new Set())}>
                  取消选择
                </Button>
              </div>
            )}
            <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
                {isAdmin && (
                  <th className="py-2.5 px-3 w-10">
                    <input
                      type="checkbox"
                      className="cursor-pointer accent-[var(--brand)]"
                      checked={list.length > 0 && list.every((d) => selected.has(d.id))}
                      onChange={(e) =>
                        setSelected(e.target.checked ? new Set(list.map((d) => d.id)) : new Set())
                      }
                    />
                  </th>
                )}
                <th className="py-2.5 px-3 font-medium">名称</th>
                <th className="py-2.5 px-3 font-medium">用例数</th>
                <th className="py-2.5 px-3 font-medium">上传人</th>
                <th className="py-2.5 px-3 font-medium">上传时间</th>
                <th className="py-2.5 px-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-hover)]">
                  {isAdmin && (
                    <td className="py-3 px-3">
                      <input
                        type="checkbox"
                        className="cursor-pointer accent-[var(--brand)]"
                        checked={selected.has(d.id)}
                        onChange={() => toggleSelect(d.id)}
                      />
                    </td>
                  )}
                  <td className="py-3 px-3 text-[var(--color-title)] font-medium">
                    <button
                      onClick={() => setDetailId(d.id)}
                      className="cursor-pointer hover:text-[var(--brand)]"
                      title="查看详情"
                    >
                      {d.name}
                    </button>
                  </td>
                  <td className="py-3 px-3">{formatNumber(d.case_count)}</td>
                  <td className="py-3 px-3">{d.username || "-"}</td>
                  <td className="py-3 px-3 text-[var(--color-muted)]">{formatDateTime(d.created_at)}</td>
                  <td className="py-3 px-3">
                    <div className="flex items-center justify-end gap-1.5">
                      <Button variant="ghost" className="h-8 px-2" onClick={() => setDetailId(d.id)}>
                        <Eye size={16} /> 详情
                      </Button>
                      <Button variant="ghost" className="h-8 px-2" onClick={() => onDownload(d)}>
                        <Download size={16} /> 下载
                      </Button>
                      {canDelete(d.owner_id) && (
                        <Button
                          variant="ghost"
                          className="h-8 px-2 text-[var(--color-error)]"
                          onClick={() => setConfirmDel({ type: "single", id: d.id, name: d.name })}
                        >
                          <Trash2 size={16} /> 删除
                        </Button>
                      )}
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
      </Card>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <DetailDialog
        datasetId={detailId}
        onClose={() => setDetailId(null)}
        onRename={(id, name) => rename.mutate({ id, name })}
        onDownload={onDownload}
      />
      <ConfirmDialog
        open={!!confirmDel}
        title="确认删除"
        message={confirmDel?.type === "batch" ? `确认删除选中的 ${confirmDel.ids.length} 个数据集及其用例？` : `确认删除数据集「${confirmDel?.name}」及其用例？`}
        onConfirm={() => {
          if (confirmDel?.type === "batch") batchDel.mutate(confirmDel.ids);
          else if (confirmDel?.type === "single") del.mutate(confirmDel.id);
          setConfirmDel(null);
        }}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  );
}

function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<unknown[][]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});

  const reset = () => {
    setFile(null);
    setName("");
    setHeaders([]);
    setRows([]);
    setMapping({});
    if (fileRef.current) fileRef.current.value = "";
  };

  const onFile = async (f: File) => {
    setFile(f);
    if (!name) setName(f.name.replace(/\.xlsx$/i, ""));
    try {
      const buf = await f.arrayBuffer();
      const wb = XLSX.read(buf);
      const ws = wb.Sheets[wb.SheetNames[0]];
      const aoa = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, defval: "" });
      const head = (aoa[0] || []).map(String);
      setHeaders(head);
      setRows(aoa.slice(1, 6));
    } catch {
      toast("error", "读取 Excel 失败");
    }
  };

  const requiredOk = REQUIRED.every(({ key }) => mapping[key]);

  const upload = useMutation({
    mutationFn: () =>
      datasets.upload(file!, name, {
        case_no: mapping.case_no,
        user_input: mapping.user_input,
        expected_gt: mapping.expected_gt,
        dimension_l1: mapping.dimension_l1 || null,
        dimension_l2: mapping.dimension_l2 || null,
      } as ColumnMapping),
    onSuccess: () => {
      toast("success", "上传成功");
      qc.invalidateQueries({ queryKey: ["datasets"] });
      reset();
      onClose();
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "上传失败"),
  });

  return (
    <Dialog
      open={open}
      title="上传数据集"
      onClose={() => { reset(); onClose(); }}
      widthClass="max-w-3xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => { reset(); onClose(); }}>取消</Button>
          <Button onClick={() => upload.mutate()} disabled={!file || !name || !requiredOk || upload.isPending}>
            {upload.isPending ? "上传中…" : "确认上传"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <div className="text-[11px] text-[var(--color-body)] mb-1.5">选择 .xlsx 文件</div>
          {file ? (
            <div className="flex items-center gap-3 h-12 px-4 rounded-[var(--radius-form)] border border-[var(--color-border)] bg-[var(--color-surface-alt)]">
              <FileSpreadsheet size={20} className="text-[var(--brand)] shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-[var(--color-title)] truncate">{file.name}</div>
                <div className="text-[11px] text-[var(--color-muted)]">{(file.size / 1024).toFixed(1)} KB</div>
              </div>
              <button
                onClick={() => { reset(); }}
                className="text-[var(--color-muted)] hover:text-[var(--color-error)] cursor-pointer shrink-0"
                title="移除文件"
              >
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
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
          />
        </div>
        <Field label="数据集名称" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>

        {headers.length > 0 && (
          <>
            <div>
              <div className="text-[11px] text-[var(--color-body)] mb-2">列映射（必填项必须映射）</div>
              <div className="grid grid-cols-2 gap-3">
                {[...REQUIRED, ...OPTIONAL].map(({ key, label }) => (
                  <Field key={key} label={label} required={REQUIRED.some((r) => r.key === key)}>
                    <Select value={mapping[key] || ""} onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))}>
                      <option value="">{REQUIRED.some((r) => r.key === key) ? "请选择列" : "（不映射）"}</option>
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
      </div>
    </Dialog>
  );
}

const CASE_HEADERS = ["用例编号", "测试输入", "预期结果", "评测一级维度", "评测二级维度"];

function DetailDialog({
  datasetId,
  onClose,
  onRename,
  onDownload,
}: {
  datasetId: string | null;
  onClose: () => void;
  onRename: (id: string, name: string) => void;
  onDownload: (d: { id: string; name: string }) => void;
}) {
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState("");
  const PAGE_SIZE = 20;
  const open = !!datasetId;

  const { data: ds, isLoading } = useQuery({
    queryKey: ["datasets", "get", datasetId],
    queryFn: () => datasets.get(datasetId!),
    enabled: open,
  });
  const { data: pageData, isLoading: casesLoading } = useQuery({
    queryKey: ["datasets", "cases", datasetId, page],
    queryFn: () => datasets.cases(datasetId!, { page, page_size: PAGE_SIZE }),
    enabled: open,
  });

  // 打开时重置分页与编辑态
  useEffect(() => {
    if (open) { setPage(1); setEditing(false); setDraftName(""); }
  }, [open]);
  // 数据集加载后初始化名称草稿
  useEffect(() => {
    if (ds && !editing) setDraftName(ds.name);
  }, [ds?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const cases = pageData?.items ?? [];
  const total = pageData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const saveName = () => {
    const n = draftName.trim();
    if (!n || !ds || n === ds.name) { setEditing(false); setDraftName(ds?.name || ""); return; }
    onRename(ds.id, n);
    setEditing(false);
  };

  return (
    <Dialog
      open={open}
      title={
        editing ? (
          <span className="flex items-center gap-2">
            <Input
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              className="h-8 w-64"
              autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") saveName(); if (e.key === "Escape") setEditing(false); }}
            />
            <Button className="h-8 px-3" onClick={saveName} disabled={!draftName.trim()}>保存</Button>
            <Button variant="ghost" className="h-8 px-3" onClick={() => { setEditing(false); setDraftName(ds?.name || ""); }}>取消</Button>
          </span>
        ) : (
          <span className="flex items-center gap-2">
            {ds?.name || "数据集详情"}
            {ds && (
              <button
                onClick={() => setEditing(true)}
                className="text-[var(--color-muted)] hover:text-[var(--brand)] cursor-pointer"
                title="改名"
              >
                <Pencil size={14} />
              </button>
            )}
          </span>
        )
      }
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
      {isLoading || casesLoading ? (
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
                    <th key={h} className="py-2.5 px-3 font-medium whitespace-nowrap">{h}</th>
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
        <EmptyState title="暂无数据" />
      )}
    </Dialog>
  );
}
