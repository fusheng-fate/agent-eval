import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Eye, Trash2, FileDown } from "lucide-react";
import { reports } from "../../lib/api";
import { ApiError } from "../../lib/http";
import { useAuth } from "../../context/AuthContext";
import { formatScore, formatDateTime, formatNumber } from "../../lib/utils";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { EmptyState } from "../../components/ui/EmptyState";
import { Pagination } from "../../components/ui/Pagination";
import { toast } from "../../components/ui/Toast";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";

// 秒数 → 可读耗时（如 8m 49s / 45s / -）
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

export default function Reports() {
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
  const [confirmDel, setConfirmDel] = useState<{ id: string; name: string } | null>(null);

  const { data: pageData, isLoading } = useQuery({
    queryKey: ["reports", "list", keyword, page, pageSize],
    queryFn: () => reports.list({ keyword: keyword || undefined, page, page_size: pageSize }),
  });
  const list = pageData?.items ?? [];
  const total = pageData?.total ?? 0;

  // 筛选条件或每页数量变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [keyword, pageSize]);

  const del = useMutation({
    mutationFn: (id: string) => reports.remove(id),
    onSuccess: () => {
      toast("success", "已删除");
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: (e) => toast("error", e instanceof ApiError ? e.message : "删除失败"),
  });

  return (
    <div>
    <Card title="报告中心">
      <div className="flex flex-wrap items-end gap-4 mb-4">
        <div className="min-w-[220px] max-w-xs">
          <label className="block text-[11px] text-[var(--color-body)] mb-1.5">任务名称</label>
          <div className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]" />
            <Input className="pl-9" placeholder="按任务名称搜索" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
          </div>
        </div>
      </div>

      {isLoading ? (
        <EmptyState title="加载中…" />
      ) : !list || list.length === 0 ? (
        <EmptyState title="暂无报告" hint="任务全部完成后自动生成报告" />
      ) : (
        <>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-[var(--color-muted)] text-[11px] border-b border-[var(--color-border)]">
              <th className="py-2.5 px-3 font-medium">报告编号</th>
              <th className="py-2.5 px-3 font-medium w-[160px] min-w-[160px] max-w-[160px]">关联任务</th>
              <th className="py-2.5 px-3 font-medium">测试人员</th>
              <th className="py-2.5 px-3 font-medium">执行通过/失败</th>
              <th className="py-2.5 px-3 font-medium">加权得分</th>
              <th className="py-2.5 px-3 font-medium">执行耗时</th>
              <th className="py-2.5 px-3 font-medium">打分耗时</th>
              <th className="py-2.5 px-3 font-medium">Token用量</th>
              <th className="py-2.5 px-3 font-medium">创建时间</th>
              <th className="py-2.5 px-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.id} className="border-b border-[var(--color-border)] last:border-0">
                <td className="py-3 px-3 text-[var(--color-muted)] font-mono text-[11px]">{r.id.slice(0, 8)}</td>
                <td className="py-3 px-3 w-[160px] min-w-[160px] max-w-[160px] truncate text-[var(--color-title)] font-medium" title={r.task_name}>{r.task_name || "-"}</td>
                <td className="py-3 px-3">{r.username || "-"}</td>
                <td className="py-3 px-3 whitespace-nowrap">
                  <span className="text-[var(--color-success)]">{r.summary?.passed ?? 0}</span>
                  <span className="text-[var(--color-muted)]"> / </span>
                  <span className="text-[var(--color-error)]">{r.summary?.failed ?? 0}</span>
                </td>
                <td className="py-3 px-3">{formatScore(r.summary?.overallScore)}</td>
                <td className="py-3 px-3 text-[var(--color-muted)] whitespace-nowrap">{formatSec(r.summary?.execSec)}</td>
                <td className="py-3 px-3 text-[var(--color-muted)] whitespace-nowrap">{formatSec(r.summary?.scoreSec)}</td>
                <td className="py-3 px-3">{formatNumber(r.summary?.tokenUsage)}</td>
                <td className="py-3 px-3 text-[var(--color-muted)] whitespace-nowrap">{formatDateTime(r.created_at)}</td>
                <td className="py-3 px-3" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1.5">
                    <Button variant="ghost" className="h-8 px-2" onClick={() => navigate(`/reports/${r.id}`)}>
                      <Eye size={16} /> 查看
                    </Button>
                    <Button
                      variant="ghost"
                      className="h-8 px-2"
                      onClick={() =>
                        reports
                          .exportHtml(r.id)
                          .then(() => toast("success", "开始下载"))
                          .catch((e) => toast("error", e instanceof ApiError ? e.message : "导出失败"))
                      }
                    >
                      <FileDown size={16} /> 导出HTML
                    </Button>
                    {isAdmin && (
                      <Button
                        variant="ghost"
                        className="h-8 px-2 text-[var(--color-error)]"
                        onClick={() => setConfirmDel({ id: r.id, name: r.task_name })}
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
    <ConfirmDialog
      open={!!confirmDel}
      title="确认删除"
      message={`确认删除报告「${confirmDel?.name}」？`}
      onConfirm={() => {
        if (confirmDel) del.mutate(confirmDel.id);
        setConfirmDel(null);
      }}
      onCancel={() => setConfirmDel(null)}
    />
  </div>
  );
}
