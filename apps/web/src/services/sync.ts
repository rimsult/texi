import type { LocalStore } from "./store";

export type SyncState = "disabled" | "idle" | "syncing" | "offline" | "error";

export interface SyncStatus {
  state: SyncState;
  pending: number;
  lastSyncedAt: number | null;
}

interface Options {
  apiUrl?: string;
  store: LocalStore;
  fetchImpl?: typeof fetch;
  isOnline?: () => boolean;
  batchSize?: number;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
}

/**
 * Pushes queued attempt events to the API whenever the network is available.
 * Events are immutable and carry UUIDs, so retries are idempotent and there
 * are no merge conflicts: the server simply ignores duplicates.
 */
export class SyncManager {
  private status: SyncStatus = { state: "idle", pending: 0, lastSyncedAt: null };
  private listeners = new Set<(s: SyncStatus) => void>();
  private running: Promise<void> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private backoff: number;
  private readonly initialBackoffMs: number;
  private readonly apiUrl?: string;
  private readonly fetchImpl: typeof fetch;
  private readonly isOnline: () => boolean;
  private readonly batchSize: number;
  private readonly maxBackoffMs: number;
  private readonly store: LocalStore;

  constructor(opts: Options) {
    this.apiUrl = opts.apiUrl?.replace(/\/$/, "") || undefined;
    this.store = opts.store;
    this.fetchImpl = opts.fetchImpl ?? ((...a) => fetch(...a));
    this.isOnline = opts.isOnline ?? (() => (typeof navigator === "undefined" ? true : navigator.onLine));
    this.batchSize = opts.batchSize ?? 200;
    this.maxBackoffMs = opts.maxBackoffMs ?? 60_000;
    this.initialBackoffMs = this.backoff = opts.initialBackoffMs ?? 1000;
    if (!this.apiUrl) this.status.state = "disabled";
  }

  get current(): SyncStatus {
    return this.status;
  }

  subscribe(fn: (s: SyncStatus) => void): () => void {
    this.listeners.add(fn);
    fn(this.status);
    return () => this.listeners.delete(fn);
  }

  /** Wire browser events; returns a cleanup function. */
  start(intervalMs = 60_000): () => void {
    const onOnline = () => void this.flush();
    const onOffline = () => void this.update({ state: this.apiUrl ? "offline" : "disabled" });
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    const timer = setInterval(() => void this.flush(), intervalMs);
    void this.flush();
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      clearInterval(timer);
      if (this.retryTimer) clearTimeout(this.retryTimer);
    };
  }

  flush(): Promise<void> {
    this.running ??= this.run().finally(() => (this.running = null));
    return this.running;
  }

  private async run(): Promise<void> {
    const pending = await this.store.pendingCount();
    if (!this.apiUrl) return this.update({ state: "disabled", pending });
    if (!this.isOnline()) return this.update({ state: "offline", pending });
    if (pending === 0) return this.update({ state: "idle", pending });
    this.update({ state: "syncing", pending });
    const deviceId = await this.store.deviceId();
    try {
      for (;;) {
        const events = await this.store.pendingEvents(this.batchSize);
        if (events.length === 0) break;
        const res = await this.fetchImpl(`${this.apiUrl}/v1/sync`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ deviceId, events }),
        });
        if (!res.ok) throw new Error(`sync failed: ${res.status}`);
        const body = (await res.json()) as { accepted: string[]; duplicates: string[]; rejected?: string[] };
        // Rejected events failed server validation and never will pass: drop them too,
        // otherwise one bad event would be resent forever and block the outbox.
        const sent = new Set(events.map((e) => e.id));
        const done = [...body.accepted, ...body.duplicates, ...(body.rejected ?? [])].filter((id) => sent.has(id));
        if (done.length === 0) throw new Error("sync made no progress");
        await this.store.acknowledge(done);
        this.update({ pending: await this.store.pendingCount() });
      }
      this.backoff = this.initialBackoffMs;
      this.update({ state: "idle", pending: 0, lastSyncedAt: Date.now() });
    } catch {
      this.update({ state: this.isOnline() ? "error" : "offline", pending: await this.store.pendingCount() });
      this.scheduleRetry();
    }
  }

  private scheduleRetry() {
    if (this.retryTimer) return;
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, this.maxBackoffMs);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.flush();
    }, delay);
  }

  private update(patch: Partial<SyncStatus>) {
    this.status = { ...this.status, ...patch };
    this.listeners.forEach((fn) => fn(this.status));
  }
}
