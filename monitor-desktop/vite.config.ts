import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import electron from "vite-plugin-electron"
import renderer from "vite-plugin-electron-renderer"
import path from "node:path"

export default defineConfig({
  plugins: [
    react(),
    electron([
      {
        // 主进程
        entry: "src/main/index.ts",
        vite: {
          build: {
            outDir: "dist-electron/main",
            rollupOptions: {
              external: ["electron", "systeminformation"],
            },
          },
        },
      },
      {
        // 预加载
        entry: "src/preload/index.ts",
        onstart(args) {
          args.reload()
        },
        vite: {
          build: {
            outDir: "dist-electron/preload",
            rollupOptions: {
              external: ["electron"],
            },
          },
        },
      },
    ]),
    renderer(),
  ],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src/renderer/src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
})