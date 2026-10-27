"use client";

import { useCallback } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

interface Props {
  onFile: (file: File) => void;
  disabled: boolean;
}

// same default as the hosted API; override per deploy with NEXT_PUBLIC_MAX_FILE_SIZE_MB
export const MAX_FILE_SIZE_MB = Number(process.env.NEXT_PUBLIC_MAX_FILE_SIZE_MB) || 50;
// .gz/.zip hold one log; the API unpacks them (with its own size cap)
export const LOG_EXTENSIONS = [".ulg", ".ulog", ".bin", ".log", ".tlog", ".bbl", ".bfl", ".txt", ".dat", ".gz", ".zip"];

const CHIPS = ["px4", "ardupilot", "mavlink", "betaflight", "dji", "compressed"] as const;

export function DropZone({ onFile, disabled }: Props) {
  const t = useTranslations("dropzone");

  const rejectionText = (r: FileRejection) => {
    const code = r.errors[0]?.code;
    if (code === "file-too-large") return t("tooLarge", { name: r.file.name, mb: MAX_FILE_SIZE_MB });
    if (code === "file-invalid-type") return t("invalidType", { name: r.file.name });
    if (code === "too-many-files") return t("tooMany");
    return r.errors[0]?.message ?? t("rejected");
  };

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) onFile(accepted[0]);
    },
    [onFile]
  );

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    accept: { "application/octet-stream": LOG_EXTENSIONS },
    maxFiles: 1,
    maxSize: MAX_FILE_SIZE_MB * 1024 * 1024,
    disabled,
  });

  return (
    <div>
      <div
        {...getRootProps()}
        className={cn(
          "flex cursor-pointer flex-col items-center rounded border-2 border-dashed px-4 py-10 text-center transition-colors",
          isDragActive ? "border-accent bg-accent/10" : "border-border hover:border-fg-subtle",
          disabled && "cursor-not-allowed opacity-50"
        )}
      >
        <input {...getInputProps()} aria-label={t("inputLabel")} />
        <Upload aria-hidden className="mb-3 h-6 w-6 text-accent" />
        <p className="font-medium">{isDragActive ? t("dropHere") : t("prompt")}</p>
        <ul className="mt-3 flex flex-wrap justify-center gap-1.5 text-2xs text-fg-muted">
          {CHIPS.map((c) => (
            <li key={c} className="rounded-sm border px-1.5 py-px">{t(`chips.${c}`)}</li>
          ))}
          <li className="num rounded-sm border px-1.5 py-px">{t("maxSize", { mb: MAX_FILE_SIZE_MB })}</li>
        </ul>
      </div>

      {fileRejections[0] && (
        <p role="alert" className="mt-2 text-xs text-critical">
          {rejectionText(fileRejections[0])}
        </p>
      )}
    </div>
  );
}
