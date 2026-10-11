import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Pitwall React dashboard.
//
// Base path: `npm run build` builds for /next/ (where FastAPI serves this app before the switch-over from the Svelte
// dashboard in web/); `npm run build:root` (`vite build --mode root`) builds for '/'. The base comes from the Vite mode
// rather than an inline `VAR=value` prefix so the script also runs where npm uses cmd.exe (Windows). `vite build --mode
// root` is still a production build: Vite sets NODE_ENV=production for every `vite build` whatever the mode, and no
// .env.root file exists. PITWALL_BASE still overrides the base for any other mode (default /next/).
// After the switch-over FastAPI serves the same dist at '/' and, for a week, at '/next/' as an alias, so a root build
// works at both addresses (/next/index.html loads /assets/* from the '/' mount; README "Switch-over"). Nothing in src
// depends on the base (switchover.test.ts). Routing is hash-based (#/drive, #/review/...), so the server never needs a
// rewrite rule - StaticFiles(html=True) serving index.html is enough at either base.
//
// Dev: `npm run dev` proxies /api and /ws to a running `pitwall serve` (PITWALL_API, default http://127.0.0.1:8770).
// The dev server binds 127.0.0.1 only and never touches the API's port.
function normaliseBase(raw: string | undefined): string {
  const b = (raw ?? "/next/").trim() || "/";
  return `/${b.replace(/^\/+|\/+$/g, "")}/`.replace(/^\/\/$/, "/");
}

const api = process.env.PITWALL_API ?? "http://127.0.0.1:8770";
const port = Number(process.env.PITWALL_DEV_PORT ?? 5174);
const proxy = {
  "/api": { target: api, changeOrigin: false },
  "/ws": { target: api.replace(/^http/, "ws"), ws: true, changeOrigin: false },
};

export default defineConfig(({ mode }) => ({
  base: mode === "root" ? "/" : normaliseBase(process.env.PITWALL_BASE),
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: port + 1, strictPort: true, proxy },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    chunkSizeWarningLimit: 800,
  },
}));
