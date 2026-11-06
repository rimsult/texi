import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";
import { embeddedPacks, pwaStub, singleFile } from "./standalone.ts";

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig(({ mode }) => {
  const standalone = mode === "standalone";
  return {
    base: standalone ? "./" : "/",
    define: { "import.meta.env.VITE_STANDALONE": JSON.stringify(standalone ? "1" : "") },
    plugins: [
      react(),
      embeddedPacks({ enabled: standalone, dir: here("./public/packs") }),
      ...(standalone
        ? [pwaStub(), singleFile({ fileName: "Texi.html", favicon: here("./public/favicon.png") })]
        : [
            VitePWA({
              registerType: "autoUpdate",
              includeAssets: ["favicon.ico", "favicon.png", "icons/*.png"],
              manifest: {
                name: "Texi — английская лексика",
                short_name: "Texi",
                description: "Офлайн-тренажёр английской лексики A1–C2: общая и техническая лексика",
                lang: "ru",
                start_url: "/",
                display: "standalone",
                background_color: "#F5F4FB",
                theme_color: "#6E56FF",
                icons: [
                  { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
                  { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
                  { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
                ],
              },
              workbox: {
                // Precache the app shell, fonts AND every content pack so all levels work offline.
                globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2,webmanifest}", "packs/*.json"],
                maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
                navigateFallback: "/index.html",
                cleanupOutdatedCaches: true,
              },
            }),
          ]),
    ],
    publicDir: standalone ? false : "public",
    build: standalone
      ? {
          outDir: "dist-standalone",
          assetsInlineLimit: () => true, // fonts become data: URLs inside the CSS
          cssCodeSplit: false,
          rollupOptions: { output: { codeSplitting: false } },
        }
      : {},
    server: { port: 5173 },
    preview: { port: 4173 },
  };
});
