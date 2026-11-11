"use client";

import { useTranslations } from "next-intl";

interface Props {
  progress: number;
  label?: string;
  onCancel?: () => void;
}

export function UploadProgress({ progress, label, onCancel }: Props) {
  const t = useTranslations("upload");
  const pct = Math.max(0, Math.min(100, Math.round(progress)));
  return (
    <div className="py-4">
      <div className="mb-2 flex items-baseline justify-between text-sm">
        <span id="upload-label">{label ?? t("uploading")}</span>
        <span className="num text-fg-muted" aria-live="polite">{pct} %</span>
      </div>
      <div
        role="progressbar"
        aria-labelledby="upload-label"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-2 overflow-hidden rounded-sm bg-elevated"
      >
        <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
      </div>
      {onCancel && (
        <button type="button" onClick={onCancel} className="btn mt-3">
          {t("cancel")}
        </button>
      )}
    </div>
  );
}
