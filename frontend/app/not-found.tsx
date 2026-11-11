import Link from "next/link";
import { useTranslations } from "next-intl";

export default function NotFound() {
  const t = useTranslations("notFound");
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center">
      <h1 className="mb-2 text-value font-semibold">{t("title")}</h1>
      <p className="text-sm text-fg-muted">{t("body")}</p>
      <Link href="/" className="btn mt-6">{t("cta")}</Link>
    </div>
  );
}
