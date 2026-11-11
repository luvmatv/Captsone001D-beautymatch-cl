import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 5173 y 3000 son los puertos que la API y el sommelier aceptan por CORS (npm run dev / npm run dev:3000).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
});
