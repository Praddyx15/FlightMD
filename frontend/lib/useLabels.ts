import { useMemo } from "react";
import { useMessages } from "next-intl";
import { makeLabels, type Labels } from "./metricLabels";

export function useLabels(): Labels {
  const messages = useMessages();
  return useMemo(() => makeLabels(messages), [messages]);
}
