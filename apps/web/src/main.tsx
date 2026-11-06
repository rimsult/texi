import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import embeddedPacks from "virtual:lexi-embedded-packs";
import { registerSW } from "virtual:pwa-register";
import { App } from "./App";
import { createServices, type Services } from "./services";
import { ContentService } from "./services/content";
import { createEmbeddedFetch } from "./services/embedded";
import "./fonts.css";
import "./styles.css";

const STANDALONE = import.meta.env.VITE_STANDALONE === "1";

// The standalone page carries all content inside itself, so it is "offline-ready" at once.
let offlineReady = STANDALONE;
const listeners = new Set<() => void>();
if (!STANDALONE) {
  registerSW({
    immediate: true,
    onOfflineReady() {
      offlineReady = true;
      listeners.forEach((l) => l());
    },
  });
  // A controlling service worker means the precache from a previous visit is in place.
  if ("serviceWorker" in navigator && navigator.serviceWorker.controller) offlineReady = true;
}

function Root({ services }: { services: Services }) {
  const [ready, setReady] = useState(offlineReady);
  useEffect(() => {
    const l = () => setReady(true);
    listeners.add(l);
    return () => void listeners.delete(l);
  }, []);
  return <App services={services} offlineReady={ready} />;
}

async function boot() {
  const overrides: Parameters<typeof createServices>[0] = {};
  if (STANDALONE && embeddedPacks) {
    overrides.content = new ContentService("packs/", createEmbeddedFetch(embeddedPacks));
    overrides.apiUrl = ""; // single-file mode: progress stays on this device
    overrides.dbName = "lexi-standalone";
  }
  const services = await createServices(overrides);
  (window as unknown as { __lexi?: Services }).__lexi = services; // e2e/debug hook
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <Root services={services} />
    </StrictMode>,
  );
}

void boot();
