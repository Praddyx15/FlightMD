import { getRequestConfig } from "next-intl/server";

export const LOCALES = ["en"] as const;
export const DEFAULT_LOCALE = "en";

// No locale in the URL. With a second language, pick it here from a cookie or
// Accept-Language; messages/<locale>.json must hold every key en.json has.
export default getRequestConfig(async () => {
  const locale = DEFAULT_LOCALE;
  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
