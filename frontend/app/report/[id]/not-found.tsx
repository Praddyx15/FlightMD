import { Clock } from "lucide-react";
import { useTranslations } from "next-intl";
import { Problem } from "@/components/report/Problem";

export default function ReportNotFound() {
  const t = useTranslations("report");
  return (
    <Problem title={t("expiredTitle")}>
      <p className="flex items-center justify-center gap-1">
        <Clock aria-hidden className="h-4 w-4" />
        {t("expiredBody")}
      </p>
    </Problem>
  );
}
