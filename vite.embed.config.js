import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds a single self-contained script for direct embedding on a host
// page (e.g. via a WordPress template), as an alternative to the iframe
// embed built by the default vite.config.js. React/ReactDOM/d3/scrollama
// are all bundled in (not externalized) — the host page isn't assumed to
// provide any of them.
export default defineConfig({
  plugins: [react()],
  // The default app build gets this from Vite's own dev/build mode handling
  // automatically; library mode doesn't inject it the same way, and React
  // reads it at runtime — without this it throws "process is not defined"
  // the moment the bundle loads on a host page (no build tooling of its
  // own to have defined `process` for it).
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    outDir: "dist-embed",
    cssCodeSplit: false,
    lib: {
      entry: "src/embed.jsx",
      name: "KCRHASystemFlowDashboard",
      formats: ["iife"],
      fileName: () => "kcrha-system-flow-dashboard.js",
    },
  },
});
