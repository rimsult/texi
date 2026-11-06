/**
 * Vite plugins for the single-file build (`npm run build:standalone` → dist-standalone/Texi.html):
 * the whole app — JS, CSS, fonts and every content pack — in one HTML file that
 * works from disk (file://) without a server, a service worker or an API.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import type { Plugin } from "vite";

const PACKS_ID = "virtual:lexi-embedded-packs";

/** Content packs as gzip+base64 strings (decoded in the browser with DecompressionStream). */
export function embeddedPacks(opts: { enabled: boolean; dir: string }): Plugin {
  return {
    name: "lexi-embedded-packs",
    resolveId: (id) => (id === PACKS_ID ? "\0" + PACKS_ID : null),
    load(id) {
      if (id !== "\0" + PACKS_ID) return null;
      if (!opts.enabled) return "export default null;";
      const files = readdirSync(opts.dir).filter((f) => f.endsWith(".json")).sort();
      const packs: Record<string, string> = {};
      for (const f of files) packs[f] = gzipSync(readFileSync(join(opts.dir, f)), { level: 9 }).toString("base64");
      return `export default ${JSON.stringify(packs)};`;
    },
  };
}

/** No service worker in the single file: stub the PWA registration module. */
export function pwaStub(): Plugin {
  const id = "virtual:pwa-register";
  return {
    name: "lexi-pwa-stub",
    enforce: "pre",
    resolveId: (s) => (s === id ? "\0" + id : null),
    load: (s) => (s === "\0" + id ? "export function registerSW() { return () => Promise.resolve(); }" : null),
  };
}

const escapeScript = (code: string) => code.replace(/<\/script/gi, "<\\/script").replace(/<!--/g, "<\\!--");

/** Inline the emitted JS/CSS into index.html, inline the favicon, and name the file. */
export function singleFile(opts: { fileName: string; favicon: string }): Plugin {
  return {
    name: "lexi-single-file",
    apply: "build",
    enforce: "post",
    transformIndexHtml(html) {
      const type = opts.favicon.endsWith(".svg") ? "image/svg+xml" : "image/png";
      const icon = `<link rel="icon" href="data:${type};base64,${readFileSync(opts.favicon).toString("base64")}" type="${type}" />`;
      return html
        .replace(/(\s*)<link rel="icon"[^>]*>/, (_m, space: string) => `${space}${icon}`)
        .replace(/\s*<link rel="(?:icon|apple-touch-icon)"(?! href="data:)[^>]*>/g, "");
    },
    generateBundle(_options, bundle) {
      const htmlAsset = bundle["index.html"];
      if (!htmlAsset || htmlAsset.type !== "asset") return;
      let html = String(htmlAsset.source);
      for (const [name, item] of Object.entries(bundle)) {
        if (item.type === "chunk" && item.isEntry) {
          const tag = new RegExp(`<script[^>]*src="[^"]*${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*></script>`);
          html = html.replace(tag, () => `<script type="module">${escapeScript(item.code)}</script>`);
          delete bundle[name];
        } else if (item.type === "asset" && name.endsWith(".css")) {
          const tag = new RegExp(`<link[^>]*href="[^"]*${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"[^>]*>`);
          html = html.replace(tag, () => `<style>${String(item.source)}</style>`);
          delete bundle[name];
        }
      }
      const leftovers = Object.keys(bundle).filter((n) => n !== "index.html");
      if (leftovers.length) this.error(`single-file build left external files: ${leftovers.join(", ")}`);
      delete bundle["index.html"];
      this.emitFile({ type: "asset", fileName: opts.fileName, source: html });
    },
  };
}
