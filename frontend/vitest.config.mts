import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}"],
    // next-intl imports next/navigation without an extension, which Node's ESM resolver
    // refuses; letting Vite bundle it resolves the path
    server: { deps: { inline: ["next-intl"] } },
  },
});
