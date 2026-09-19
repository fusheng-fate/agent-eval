import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, Info } from "lucide-react";
import { cn } from "../../lib/utils";

type ToastType = "success" | "error" | "info";
interface ToastItem {
  id: number;
  type: ToastType;
  msg: string;
}

const EVT = "app:toast";
let seq = 0;

export function toast(type: ToastType, msg: string): void {
  window.dispatchEvent(new CustomEvent(EVT, { detail: { id: ++seq, type, msg } }));
}

const icons = {
  success: <CheckCircle2 size={18} className="text-[var(--color-success)]" />,
  error: <XCircle size={18} className="text-[var(--color-error)]" />,
  info: <Info size={18} className="text-[var(--intl-blue)]" />,
};

export function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const onToast = (e: Event) => {
      const detail = (e as CustomEvent).detail as ToastItem;
      setItems((prev) => [...prev, detail]);
      setTimeout(() => setItems((prev) => prev.filter((i) => i.id !== detail.id)), 3000);
    };
    window.addEventListener(EVT, onToast);
    return () => window.removeEventListener(EVT, onToast);
  }, []);

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2">
      {items.map((i) => (
        <div
          key={i.id}
          className={cn(
            "flex items-center gap-2 bg-white rounded-[var(--radius-form)] px-4 py-3 shadow-[var(--shadow-card)] text-[11px] text-[var(--color-title)] fade-in"
          )}
        >
          {icons[i.type]}
          <span>{i.msg}</span>
        </div>
      ))}
    </div>
  );
}
