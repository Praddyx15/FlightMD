import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

// Full-page message for a report that can't be shown. Renders on the server too; only
// the client island passes `retry`.
export function Problem({ title, children, retry }: { title: string; children: React.ReactNode; retry?: () => void }) {
  const t = useTranslations("report");
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center" role="alert">
      <h1 className="mb-2 flex items-center justify-center gap-2 text-value font-semibold">
        <AlertTriangle aria-hidden className="h-5 w-5 text-caution" />
        {title}
      </h1>
      <div className="text-sm text-fg-muted">{children}</div>
      <div className="mt-6 flex justify-center gap-2">
        {retry && <button type="button" onClick={retry} className="btn-primary">{t("retry")}</button>}
        <Link href="/" className="btn">{t("analyseAnother")}</Link>
      </div>
    </div>
  );
}

// A failed analysis. The API marks jobs cut off by a restart with "interrupted...".
export function FailedProblem({ error }: { error: string | null }) {
  const t = useTranslations("report");
  const text = !error ? t("failedDefault") : /^interrupted/i.test(error) ? t("interrupted") : error;
  return <Problem title={t("failedTitle")}>{text}</Problem>;
}
