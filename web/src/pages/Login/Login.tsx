import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { ApiError } from "../../lib/http";
import { toast } from "../../components/ui/Toast";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState(() => localStorage.getItem("login_user") || "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    try {
      localStorage.setItem("login_user", username);
      await login(username, password);
      const redirect = params.get("redirect");
      navigate(redirect && redirect.startsWith("/") ? redirect : "/", { replace: true });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "登录失败";
      toast("error", msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-white rounded-[var(--radius-card)] p-8 w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <span className="w-12 h-12 rounded-xl bg-[var(--brand)] text-white text-base font-bold flex items-center justify-center mb-3">
            A
          </span>
          <h1 className="text-[20px] font-semibold text-[var(--color-title)] m-0">Agent 评测平台</h1>
          <p className="text-[11px] text-[var(--color-muted)] mt-1">登录后开始评测</p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">用户名</label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="请输入用户名" autoFocus />
          </div>
          <div>
            <label className="block text-[11px] text-[var(--color-body)] mb-1.5">密码</label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
            />
          </div>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "登录中…" : "登录"}
          </Button>
        </form>
      </div>
    </div>
  );
}
