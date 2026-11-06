import { useEffect, useState } from "react";
import type { SyncManager, SyncStatus } from "../services/sync";

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

export function useSyncStatus(sync: SyncManager): SyncStatus {
  const [status, setStatus] = useState(sync.current);
  useEffect(() => sync.subscribe(setStatus), [sync]);
  return status;
}
