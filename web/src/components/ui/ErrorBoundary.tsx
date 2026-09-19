import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="bg-white rounded-[var(--radius-card)] p-8 max-w-md text-center">
            <div className="text-[17px] font-semibold text-[var(--color-title)] mb-2">页面出错了</div>
            <pre className="text-[11px] text-[var(--color-error)] text-left whitespace-pre-wrap mb-4">
              {this.state.error.message}
            </pre>
            <button
              onClick={() => window.location.reload()}
              className="h-10 px-4 rounded-[var(--radius-form)] bg-[var(--brand)] text-white text-[11px] cursor-pointer"
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
