// 占位符插入面板：列出可插入的占位符（全局变量 / 各步骤输出 / token）。
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/utils";
import type { ChainModel } from "./types";

type PhItem = { code: string; desc: string };
type PhGroup = { title: string; items: PhItem[] };

function phGroups(model: ChainModel): PhGroup[] {
  const groups: PhGroup[] = [];
  const vars = Object.keys(model.variables || {});
  if (vars.length) {
    groups.push({ title: "全局变量", items: vars.map((k) => ({ code: `{{vars.${k}}}`, desc: k })) });
  }
  model.steps.forEach((s) => {
    const api = model.apis.find((a) => a.id === s.api_id);
    const outs = api && api.extract ? Object.keys(api.extract) : [];
    const items: PhItem[] = outs.map((o) => ({ code: `{{steps.${s.id}.${o}}}`, desc: o }));
    items.push({ code: `{{steps.${s.id}.status_code}}`, desc: "状态码" });
    items.push({ code: `{{steps.${s.id}.body}}`, desc: "响应体" });
    groups.push({ title: `步骤 ${s.id} (${s.api_id})`, items });
  });
  groups.push({ title: "其他", items: [{ code: "{{token}}", desc: "当前 token" }] });
  return groups;
}

type PlaceholderPanelProps = {
  model: ChainModel;
  onInsert: (code: string) => void;
  className?: string;
};

const PANEL_W = 288; // w-72
const PANEL_MAX_H = 288; // max-h-72
const MARGIN = 8; // 视口边缘留白

export function PlaceholderPanel({ model, onInsert, className }: PlaceholderPanelProps) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  // 打开时按按钮位置计算下拉坐标，贴边时翻转到上方/收进视口
  useLayoutEffect(() => {
    if (!open) return;
    const btn = btnRef.current;
    const panel = panelRef.current;
    if (!btn || !panel) return;
    const r = btn.getBoundingClientRect();
    const spaceBelow = window.innerHeight - r.bottom;
    const dropUp = spaceBelow < 120 && r.top > spaceBelow;
    let left = r.left;
    if (left + PANEL_W > window.innerWidth - MARGIN) {
      left = Math.max(MARGIN, window.innerWidth - PANEL_W - MARGIN);
    }
    const top = dropUp ? r.top - panel.offsetHeight - 4 : r.bottom + 4;
    setPos({ top, left });
  }, [open]);

  // 打开期间滚动/缩放时跟随按钮（捕获阶段，滚动发生在内部容器也能监听到）
  useEffect(() => {
    if (!open) return;
    const reposition = () => {
      const btn = btnRef.current;
      const panel = panelRef.current;
      if (!btn || !panel) return;
      const r = btn.getBoundingClientRect();
      const spaceBelow = window.innerHeight - r.bottom;
      const dropUp = spaceBelow < 120 && r.top > spaceBelow;
      let left = r.left;
      if (left + PANEL_W > window.innerWidth - MARGIN) {
        left = Math.max(MARGIN, window.innerWidth - PANEL_W - MARGIN);
      }
      const top = dropUp ? r.top - panel.offsetHeight - 4 : r.bottom + 4;
      setPos({ top, left });
    };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (btnRef.current && btnRef.current.contains(e.target as Node)) return;
      if (panelRef.current && panelRef.current.contains(e.target as Node)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const groups = phGroups(model);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className={cn(
          "rounded-[var(--radius-form)] border border-[var(--input-border)] px-1.5 py-0.5 text-[8px] font-semibold text-[var(--brand)] hover:bg-[var(--color-hover)] cursor-pointer",
          className
        )}
      >
        插入占位符
      </button>
      {open &&
        createPortal(
          <div
            ref={panelRef}
            style={{ top: pos.top, left: pos.left, width: PANEL_W, maxHeight: PANEL_MAX_H }}
            className="fixed z-[100] overflow-auto rounded-[var(--radius-form)] border border-[var(--color-border)] bg-white p-2 shadow-lg"
          >
            {groups.map((g) => (
              <div key={g.title} className="mb-2">
                <div className="mb-1 text-[8px] font-semibold text-[var(--color-muted)]">{g.title}</div>
                {g.items.length === 0 ? (
                  <div className="text-[8px] text-[var(--color-muted)]">无</div>
                ) : (
                  <div className="space-y-0.5">
                    {g.items.map((it) => (
                      <button
                        key={it.code}
                        type="button"
                        onClick={() => {
                          onInsert(it.code);
                          setOpen(false);
                        }}
                        className="flex w-full items-center justify-between gap-2 rounded-[var(--radius-form)] px-2 py-1 text-left hover:bg-[var(--color-hover)] cursor-pointer"
                      >
                        <code className="truncate text-[8px] text-[var(--color-title)]">{it.code}</code>
                        <span className="shrink-0 text-[8px] text-[var(--color-muted)]">{it.desc}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>,
          document.body
        )}
    </>
  );
}
