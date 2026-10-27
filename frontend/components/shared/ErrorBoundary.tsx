"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  // short noun for the message, e.g. "Chart" -> "Chart unavailable"
  what?: string;
  fallback?: ReactNode;
}

// Keeps one malformed chart or section from blanking the whole report.
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(err: unknown) {
    console.error(err);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      this.props.fallback ?? (
        <div role="status" className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-xs text-fg-muted">
          <AlertTriangle aria-hidden className="h-4 w-4 text-caution" />
          {this.props.what ?? "This section"} unavailable: the data in this report could not be drawn.
        </div>
      )
    );
  }
}
