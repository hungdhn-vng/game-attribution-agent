import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/gaa/**/*.test.ts"],
    pool: "forks",
    environmentMatchGlobs: [["tests/gaa/store.test.ts", "jsdom"]],
  },
});
