"use client";

import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { formatFileSize } from "@/lib/utils";

interface Props {
  onFile: (file: File) => void;
  disabled: boolean;
}

export function DropZone({ onFile, disabled }: Props) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) onFile(accepted[0]);
    },
    [onFile]
  );

  const { getRootProps, getInputProps, isDragActive, acceptedFiles, fileRejections } =
    useDropzone({
      onDrop,
      accept: {
        "application/octet-stream": [".ulg", ".ulog", ".bin", ".tlog"],
      },
      maxFiles: 1,
      maxSize: 50 * 1024 * 1024,
      disabled,
    });

  const selectedFile = acceptedFiles[0];
  const rejected = fileRejections[0];

  return (
    <div
      {...getRootProps()}
      className="relative cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition-all duration-200"
      style={{
        borderColor: isDragActive ? "var(--accent)" : "rgba(255,255,255,0.12)",
        background: isDragActive ? "rgba(142,201,112,0.05)" : "transparent",
      }}
    >
      <input {...getInputProps()} />

      {selectedFile ? (
        <div>
          <div className="text-3xl mb-3">📄</div>
          <div className="font-semibold text-white/90 mono">{selectedFile.name}</div>
          <div className="text-sm text-white/50 mt-1">{formatFileSize(selectedFile.size)}</div>
          <div className="mt-3 text-xs text-white/30">Drop another file to replace</div>
        </div>
      ) : (
        <div>
          <div className="text-4xl mb-4">{isDragActive ? "📂" : "📁"}</div>
          <p className="text-white/70 font-medium">
            {isDragActive
              ? "Drop your flight log here…"
              : "Drag & drop your flight log here"}
          </p>
          <p className="text-white/40 text-sm mt-1">or click to browse</p>
          <p className="text-white/25 text-xs mt-4">
            PX4 (.ulg) · ArduPilot (.bin) · MAVLink telemetry (.tlog) · Max 50MB
          </p>
        </div>
      )}

      {rejected && (
        <div className="mt-4 text-xs text-red-400">
          {rejected.errors[0]?.message ?? "File rejected. Check format and size."}
        </div>
      )}

      {/* Analyse button */}
      {selectedFile && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onFile(selectedFile);
          }}
          className="mt-6 px-8 py-3 rounded-lg font-semibold text-sm transition-all duration-200 hover:opacity-90 active:scale-95"
          style={{ background: "var(--accent)", color: "var(--bg-primary)" }}
        >
          Analyse Flight Log →
        </button>
      )}
    </div>
  );
}
