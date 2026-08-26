import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Base path matches the GitHub Pages project-page URL (repo name).
// Update if the deploy target changes (e.g. a custom domain uses "/").
export default defineConfig({
  plugins: [react()],
  base: "/system-flow-story/",
});
