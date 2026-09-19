// 通用工具（旧版缺失，重建）。

/** 合并 className（过滤 falsy）。 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** 短唯一 id（前端临时用）。 */
export function uid(prefix = "id"): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

/** 千分位数字。 */
export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return n.toLocaleString("en-US");
}

/** 百分比（0-1 → x.x%）。 */
export function formatPercent(ratio: number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return "-";
  return `${(ratio * 100).toFixed(digits)}%`;
}

/** 分数（后端已是百分制 0-100，直接展示，保留最多 2 位）。 */
export function formatScore(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return String(Math.round(n * 100) / 100);
}

/** 时延等原始数字（保留最多 2 位，不换算分制）。 */
export function formatNumber2(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return String(Math.round(n * 100) / 100);
}

/** ISO 时间 → 本地 yyyy-MM-dd HH:mm。 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 自然排序比较器：A01 < A02 < A10 < B01（数字段按数值比，避免字典序 A10<A2）。 */
export function naturalCompare(a: string, b: string): number {
  if (a === b) return 0;
  const re = /(\d+|\D+)/g;
  const pa = a.match(re) || [];
  const pb = b.match(re) || [];
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const xa = pa[i] ?? "";
    const xb = pb[i] ?? "";
    if (xa === xb) continue;
    const na = Number(xa);
    const nb = Number(xb);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    return xa < xb ? -1 : 1;
  }
  return 0;
}

/** 两个 ISO 时间的差值 → 时长（s / m s / h m）。缺任一返回 "-"。 */
export function formatDuration(startIso: string | null | undefined, endIso: string | null | undefined): string {
  if (!startIso || !endIso) return "-";
  const s = new Date(startIso).getTime();
  const e = new Date(endIso).getTime();
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return "-";
  const sec = Math.round((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ${sec % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
