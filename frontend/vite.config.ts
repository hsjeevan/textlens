import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app calls the API under /api. In development Vite proxies that prefix to
// the FastAPI server; in the container nginx does the same (nginx.conf.template).
const apiUrl = process.env.TEXTLENS_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8501,
    proxy: {
      "/api": { target: apiUrl, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
