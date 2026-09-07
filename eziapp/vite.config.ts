import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  esbuild: {
    drop: ["console", "debugger"],
    legalComments: "none"
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    minify: "esbuild",
    cssMinify: true,
    assetsInlineLimit: 0,
    modulePreload: false,
    rollupOptions: {
      output: {
        compact: true,
        chunkFileNames: "c/[name]-[hash].js",
        entryFileNames: "e/[name]-[hash].js",
        assetFileNames: "a/[name]-[hash][extname]"
      }
    }
  },
  server: {
    host: "127.0.0.1",
    port: 5178,
    strictPort: false
  }
});