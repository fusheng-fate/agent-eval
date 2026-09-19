// 极简 Markdown 渲染（标题/列表/代码/粗体/行内代码/段落）。指标 skill_md 用。
import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  // 粗体 **x** 与行内代码 `x`
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(<Fragment key={k++}>{text.slice(last, m.index)}</Fragment>);
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    else
      parts.push(
        <code key={k++} className="bg-[var(--color-surface-alt)] px-1 py-0.5 rounded text-[11px] text-[var(--color-title)]">
          {tok.slice(1, -1)}
        </code>
      );
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(<Fragment key={k++}>{text.slice(last)}</Fragment>);
  return parts;
}

export function MarkdownView({ source }: { source: string }) {
  const lines = (source || "").split("\n");
  const out: ReactNode[] = [];
  let inCode = false;
  let codeBuf: string[] = [];
  let listBuf: string[] = [];

  const flushList = (key: string) => {
    if (listBuf.length) {
      out.push(
        <ul key={key} className="list-disc pl-5 my-2 space-y-1">
          {listBuf.map((li, i) => (
            <li key={i}>{inline(li)}</li>
          ))}
        </ul>
      );
      listBuf = [];
    }
  };

  lines.forEach((raw, idx) => {
    const line = raw;
    if (line.trim().startsWith("```")) {
      if (inCode) {
        out.push(
          <pre key={`c${idx}`} className="bg-[var(--color-surface-alt)] rounded p-3 text-[11px] overflow-x-auto my-2">
            {codeBuf.join("\n")}
          </pre>
        );
        codeBuf = [];
        inCode = false;
      } else {
        flushList(`l${idx}`);
        inCode = true;
      }
      return;
    }
    if (inCode) {
      codeBuf.push(line);
      return;
    }
    if (/^#{1,6}\s/.test(line)) {
      flushList(`l${idx}`);
      const level = line.match(/^#+/)![0].length;
      const text = line.replace(/^#+\s/, "");
      out.push(
        <div key={`h${idx}`} className="font-semibold text-[var(--color-title)] mt-3 mb-1" style={{ fontSize: `${18 - level * 1.5}px` }}>
          {inline(text)}
        </div>
      );
      return;
    }
    if (/^\s*[-*]\s/.test(line)) {
      listBuf.push(line.replace(/^\s*[-*]\s/, ""));
      return;
    }
    flushList(`l${idx}`);
    if (line.trim()) {
      out.push(<p key={`p${idx}`} className="my-1.5 leading-relaxed">{inline(line)}</p>);
    }
  });
  flushList("l-end");

  return <div className="text-[11px] text-[var(--color-body)]">{out}</div>;
}
