import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri 2 官方模板配置（dev 端口 1420 与 src-tauri/tauri.conf.json 对应）
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
});
