"use client";

import Link from "next/link";
import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("errorPage");

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center">
      <h1 className="mb-2 flex items-center justify-center gap-2 text-value font-semibold">
        <AlertTriangle aria-hidden className="h-5 w-5 text-caution" />
        {t("title")}
      </h1>
      <p className="text-sm text-fg-muted">{t("body")}</p>
      <div className="mt-6 flex justify-center gap-2">
        <button type="button" onClick={reset} className="btn-primary">{t("retry")}</button>
        <Link href="/" className="btn">{t("home")}</Link>
      </div>
    </div>
  );
}
