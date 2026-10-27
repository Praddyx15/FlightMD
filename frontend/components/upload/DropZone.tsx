"use client";

import { useCallback } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  onFile: (file: File) => void;
  disabled: boolean;
}

// same default as the hosted API; override per deploy with NEXT_PUBLIC_MAX_FILE_SIZE_MB
export const MAX_FILE_SIZE_MB = Number(process.env.NEXT_PUBLIC_MAX_FILE_SIZE_MB) || 50;
export const LOG_EXTENSIONS = [".ulg", ".ulog", ".bin", ".tlog"];

function rejectionText(r: FileRejection): string {
  const code = r.errors[0]?.code;
  if (code === "file-too-large") return `${r.file.name} is larger than ${MAX_FILE_SIZE_MB} MB.`;
  if (code === "file-invalid-type") return `${r.file.name} is not a .ulg, .bin or .tlog log.`;
  if (code === "too-many-files") return "Drop one log at a time.";
  return r.errors[0]?.message ?? "File rejected.";
}

export function DropZone({ onFile, disabled }: Props) {
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
        <input {...getInputProps()} aria-label="Flight log file" />
        <Upload aria-hidden className="mb-3 h-6 w-6 text-accent" />
        <p className="font-medium">{isDragActive ? "Drop the log here" : "Drop a flight log here, or click to choose one"}</p>
        <ul className="mt-3 flex flex-wrap justify-center gap-1.5 text-2xs text-fg-muted">
          <li className="rounded-sm border px-1.5 py-px">PX4 .ulg</li>
          <li className="rounded-sm border px-1.5 py-px">ArduPilot .bin</li>
          <li className="rounded-sm border px-1.5 py-px">MAVLink .tlog</li>
          <li className="num rounded-sm border px-1.5 py-px">max {MAX_FILE_SIZE_MB} MB</li>
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
