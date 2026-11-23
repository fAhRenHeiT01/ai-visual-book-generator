import react from "@vitejs/plugin-react";
import { existsSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    pool: "threads",
    include: ["tests/unit/**/*.test.{ts,tsx}", "tests/integration/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    onConsoleLog(_message, type) {
      if (type === "stderr") throw new Error("Console warnings and errors fail the test suite");
    },
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.d.ts"],
      reporter: ["text", "json-summary"],
      thresholds:
        existsSync(resolve("src/engine")) &&
        readdirSync(resolve("src/engine"), { recursive: true }).some(
          (name) => typeof name === "string" && (name.endsWith(".ts") || name.endsWith(".tsx")),
        )
          ? { "src/engine/**": { branches: 80 } }
          : {},
    },
  },
});
