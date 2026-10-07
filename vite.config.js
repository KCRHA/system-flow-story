import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Base path matches the GitHub Pages project-page URL (repo name).
// Update if the deploy target changes (e.g. a custom domain uses "/").
export default defineConfig({
  plugins: [react()],
  // SFS_BASE overrides it, e.g. SFS_BASE=/flow/ for a build served from another path.
  base: process.env.SFS_BASE ?? "/system-flow-story/",
});
