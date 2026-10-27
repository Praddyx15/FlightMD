"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

type What = "section" | "chart" | "charts" | "flightPath" | "map" | "view3d";

interface Props {
  children: ReactNode;
  // which thing broke, for "Chart unavailable: ..."
  what?: What;
  fallback?: ReactNode;
}

function Unavailable({ what }: { what: What }) {
  const t = useTranslations("unavailable");
  return (
    <div role="status" className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-xs text-fg-muted">
      <AlertTriangle aria-hidden className="h-4 w-4 text-caution" />
      {t("message", { what: t(what) })}
    </div>
  );
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
    return this.props.fallback ?? <Unavailable what={this.props.what ?? "section"} />;
  }
}
