import { defineConfig } from "vitest/config";

// Unit tests for the framework-agnostic data layer (src/lib): plain node, no DOM library - each test stubs the
// browser globals it needs (src/test/fakes.ts). Kept apart from vite.config.ts so tests never load the Tailwind /
// React plugins or depend on PITWALL_BASE.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
