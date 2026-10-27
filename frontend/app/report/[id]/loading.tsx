import { useTranslations } from "next-intl";

const bar = "rounded-sm bg-elevated animate-pulse reduce-motion:animate-none";

// Same outline as the finished report: header, verdict band, finding cards, parameter table.
export default function Loading() {
  const t = useTranslations("report");
  return (
    <div className="mx-auto max-w-5xl space-y-10 px-4 py-6" aria-busy="true">
      <p className="sr-only" role="status">{t("loading")}</p>

      <div className="space-y-4" aria-hidden>
        <div className="space-y-2">
          <div className={`h-7 w-2/3 max-w-md ${bar}`} />
          <div className={`h-4 w-1/2 max-w-sm ${bar}`} />
        </div>
        <div className="panel flex flex-col gap-5 p-4 sm:flex-row sm:items-center sm:p-6">
          <div className="mx-auto size-[120px] shrink-0 rounded-full border-8 border-elevated sm:mx-0" />
          <div className="flex-1 space-y-3">
            <div className="flex gap-2">
              <div className={`h-5 w-16 ${bar}`} />
              <div className={`h-5 w-24 ${bar}`} />
            </div>
            <div className={`h-4 w-full ${bar}`} />
            <div className={`h-4 w-5/6 ${bar}`} />
            <div className={`h-3 w-1/2 ${bar}`} />
          </div>
        </div>
      </div>

      <div className="space-y-2" aria-hidden>
        <div className={`h-5 w-32 ${bar}`} />
        <div className={`h-8 w-full ${bar}`} />
        {[0, 1, 2].map((n) => (
          <div key={n} className="rounded border border-l-4 bg-surface p-3">
            <div className={`mb-2 h-4 w-1/3 ${bar}`} />
            <div className={`h-3 w-3/4 ${bar}`} />
          </div>
        ))}
      </div>

      <div className="space-y-2" aria-hidden>
        <div className={`h-5 w-40 ${bar}`} />
        <div className="panel divide-y">
          {[0, 1, 2, 3].map((n) => (
            <div key={n} className="flex gap-4 px-3 py-2.5">
              <div className={`h-4 w-32 ${bar}`} />
              <div className={`ml-auto h-4 w-12 ${bar}`} />
              <div className={`h-4 w-12 ${bar}`} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
