import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately; Vite forwards its paths to it.
// In production FastAPI serves the built app, so the same relative paths work.
const api = process.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const apiPaths = ["/deals", "/sales", "/watch", "/flags", "/sim", "/registry", "/rules", "/samples", "/artworks",
  "/chain", "/assistant", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(apiPaths.map((p) => [p, { target: api, changeOrigin: true }])),
  },
});
