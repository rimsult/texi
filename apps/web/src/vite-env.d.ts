/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** "1" in the single-file build (Texi.html): packs embedded, no service worker, no sync. */
  readonly VITE_STANDALONE?: string;
}

declare module "virtual:lexi-embedded-packs" {
  /** file name -> gzip+base64 body; null outside the standalone build. */
  const packs: Record<string, string> | null;
  export default packs;
}
