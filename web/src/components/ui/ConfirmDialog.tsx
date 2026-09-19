import { Dialog } from "./Dialog";
import { Button } from "./Button";
import { AlertTriangle } from "lucide-react";

export function ConfirmDialog({
  open,
  title = "确认操作",
  message,
  confirmText = "确认",
  cancelText = "取消",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog
      open={open}
      title={title}
      onClose={onCancel}
      widthClass="max-w-sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>{cancelText}</Button>
          <Button variant="danger" onClick={onConfirm}>{confirmText}</Button>
        </>
      }
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 w-9 h-9 rounded-full bg-[#FDECEC] flex items-center justify-center">
          <AlertTriangle size={18} className="text-[var(--color-error)]" />
        </div>
        <p className="text-[11px] text-[var(--color-body)] leading-relaxed m-0 pt-1.5">{message}</p>
      </div>
    </Dialog>
  );
}
