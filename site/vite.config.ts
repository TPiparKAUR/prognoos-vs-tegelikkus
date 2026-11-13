import { defineConfig } from "vite";

// Relative base: the page works under https://<owner>.github.io/<repo>/ and from any
// sub-path of an internal GitLab Pages instance (ADR-010) without rebuilding.
export default defineConfig({
  base: "./",
  build: {
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 1800,
  },
});
