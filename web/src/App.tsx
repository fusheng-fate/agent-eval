import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import { AppLayout } from "./components/layout/AppLayout";
import { Loader2 } from "lucide-react";

import Login from "./pages/Login/Login";
import TaskCenter from "./pages/TaskCenter/TaskCenter";
import RunDetail from "./pages/RunDetail/RunDetail";
import CaseResult from "./pages/CaseResult/CaseResult";
import Evaluator from "./pages/Evaluator/Evaluator";
import Datasets from "./pages/Datasets/Datasets";
import Execution from "./pages/Execution/Execution";
import Reports from "./pages/Reports/Reports";
import ReportDetail from "./pages/Reports/ReportDetail";
import Configs from "./pages/Configs/Configs";

function FullScreenLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <Loader2 size={28} className="animate-spin text-[var(--brand)]" />
    </div>
  );
}

// 路由守卫：未登录 → /login（保留当前路径登录后回跳）。
function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <FullScreenLoader />;
  if (!user) {
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const { user, loading } = useAuth();
  return (
    <Routes>
      <Route
        path="/login"
        element={
          loading ? <FullScreenLoader /> : user ? <Navigate to="/" replace /> : <Login />
        }
      />
      <Route
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route path="/" element={<TaskCenter />} />
        <Route path="/runs/:id" element={<RunDetail />} />
        <Route path="/runs/:id/cases/:caseId" element={<CaseResult />} />
        <Route path="/evaluator" element={<Evaluator />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/execution" element={<Execution />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/reports/:id" element={<ReportDetail />} />
        <Route path="/configs" element={<Configs />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
