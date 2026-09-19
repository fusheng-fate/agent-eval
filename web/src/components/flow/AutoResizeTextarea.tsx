// 高度随内容自适应的 textarea：初始按内容撑高（不出现内部滚动条），内容变化时自动调整。
// 手动拖动（resize-y）后以用户设置的高度为准，直到内容再次变化。
import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, type TextareaHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type Props = TextareaHTMLAttributes<HTMLTextAreaElement>;

export const AutoResizeTextarea = forwardRef<HTMLTextAreaElement, Props>(function AutoResizeTextarea(
  { className, ...rest },
  ref
) {
  const innerRef = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => innerRef.current as HTMLTextAreaElement, []);

  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  });

  return <textarea ref={innerRef} className={cn("resize-y overflow-hidden", className)} {...rest} />;
});
