import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    projects: [
      { test: { name: "core", include: ["packages/core/test/**/*.test.ts"], environment: "node" } },
      {
        plugins: [react()],
        test: {
          name: "web",
          include: ["apps/web/test/**/*.test.{ts,tsx}"],
          environment: "jsdom",
          setupFiles: ["apps/web/test/setup.ts"],
        },
      },
      { test: { name: "api", include: ["apps/api/test/**/*.test.ts"], environment: "node", fileParallelism: false } },
    ],
  },
});
