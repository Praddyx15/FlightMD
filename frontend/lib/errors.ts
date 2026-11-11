import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { ApiError } from "./api";

// Error text for the UI: the server's own detail when it sent one, else ours by code.
export function useErrorText() {
  const t = useTranslations("errors");
  return useCallback(
    (e: unknown, fallback = "generic") => {
      if (e instanceof ApiError && e.code) return t(e.code, { status: e.status });
      if (e instanceof Error && e.message) return e.message;
      return t(fallback, { status: 0 });
    },
    [t]
  );
}
