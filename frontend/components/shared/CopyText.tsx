"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { copyToClipboard } from "@/lib/utils";

// A hash or id shown short, copied whole.
export function CopyText({ text, label, short = 12 }: { text: string; label: string; short?: number }) {
  const t = useTranslations("common");
  const [copied, setCopied] = useState(false);
  return (
    <span className="inline-flex items-center gap-1">
      <code className="num rounded-sm bg-elevated px-1 text-fg" title={text}>
        {text.length > short ? `${text.slice(0, short)}…` : text}
      </code>
      <button
        type="button"
        className="btn no-print px-1.5 text-xs"
        aria-label={t("copyNamed", { name: label })}
        onClick={async () => {
          try {
            await copyToClipboard(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            // the full value is still in the title attribute
          }
        }}
      >
        {copied ? <Check aria-hidden className="h-3.5 w-3.5 text-ok" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
      </button>
      <span className="print-only num break-all text-2xs">{text}</span>
    </span>
  );
}
