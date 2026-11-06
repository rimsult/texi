import { applyAnswer } from "@lexi/core";
import { describe, expect, it, vi } from "vitest";
import type { LocalStore } from "../src/services/store";
import { SyncManager } from "../src/services/sync";
import { event, makeStore } from "./helpers";

async function seeded(n: number): Promise<LocalStore> {
  const store = await makeStore();
  for (let i = 1; i <= n; i++) await store.recordAttempt(event(i), applyAnswer(undefined, event(i), true, 0));
  return store;
}

function api(handler?: (body: { deviceId: string; events: { id: string }[] }) => Response | Promise<Response>) {
  const bodies: { deviceId: string; events: { id: string }[] }[] = [];
  const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init!.body));
    bodies.push(body);
    if (handler) return handler(body);
    return Response.json({ accepted: body.events.map((e: { id: string }) => e.id), duplicates: [] });
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, bodies, spy: fetchImpl };
}

describe("SyncManager", () => {
  it("is disabled without an API url and never calls the network", async () => {
    const store = await seeded(2);
    const { fetchImpl, spy } = api();
    const sync = new SyncManager({ store, fetchImpl });
    await sync.flush();
    expect(sync.current).toMatchObject({ state: "disabled", pending: 2 });
    expect(spy).not.toHaveBeenCalled();
  });

  it("pushes the outbox in batches and clears acknowledged events", async () => {
    const store = await seeded(5);
    const { fetchImpl, bodies } = api();
    const sync = new SyncManager({ apiUrl: "https://api.test/", store, fetchImpl, isOnline: () => true, batchSize: 2 });
    const states: string[] = [];
    sync.subscribe((s) => states.push(s.state));
    await sync.flush();
    expect(bodies.map((b) => b.events.length)).toEqual([2, 2, 1]);
    expect(new Set(bodies.map((b) => b.deviceId)).size).toBe(1);
    expect(await store.pendingCount()).toBe(0);
    expect(sync.current.state).toBe("idle");
    expect(sync.current.lastSyncedAt).not.toBeNull();
    expect(states).toContain("syncing");
  });

  it("treats server-side duplicates as delivered (idempotent retries)", async () => {
    const store = await seeded(3);
    const { fetchImpl } = api((b) => Response.json({ accepted: [], duplicates: b.events.map((e) => e.id) }));
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => true });
    await sync.flush();
    expect(await store.pendingCount()).toBe(0);
  });

  it("drops events the server rejected as invalid so they cannot block the outbox", async () => {
    const store = await seeded(3);
    const { fetchImpl, bodies } = api((b) =>
      Response.json({ accepted: b.events.slice(1).map((e) => e.id), duplicates: [], rejected: [b.events[0]!.id] }),
    );
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => true });
    await sync.flush();
    expect(bodies).toHaveLength(1);
    expect(await store.pendingCount()).toBe(0);
    expect(sync.current.state).toBe("idle");
  });

  it("stops instead of looping when the server acknowledges nothing", async () => {
    const store = await seeded(2);
    const { fetchImpl, spy } = api(() => Response.json({ accepted: [], duplicates: [] }));
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => true, initialBackoffMs: 60_000 });
    await sync.flush();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(sync.current).toMatchObject({ state: "error", pending: 2 });
  });

  it("keeps everything queued while offline", async () => {
    const store = await seeded(3);
    const { fetchImpl, spy } = api();
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => false });
    await sync.flush();
    expect(sync.current).toMatchObject({ state: "offline", pending: 3 });
    expect(spy).not.toHaveBeenCalled();
  });

  it("keeps events on server errors and retries with backoff", async () => {
    const store = await seeded(2);
    let fail = true;
    const { fetchImpl, spy } = api((b) =>
      fail ? new Response("boom", { status: 500 }) : Response.json({ accepted: b.events.map((e) => e.id), duplicates: [] }),
    );
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => true, initialBackoffMs: 20 });
    await sync.flush();
    expect(sync.current).toMatchObject({ state: "error", pending: 2 });
    fail = false;
    await vi.waitFor(async () => expect(await store.pendingCount()).toBe(0), { timeout: 2000 });
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(sync.current.state).toBe("idle");
  });

  it("coalesces concurrent flushes", async () => {
    const store = await seeded(1);
    const { fetchImpl, spy } = api();
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => true });
    await Promise.all([sync.flush(), sync.flush(), sync.flush()]);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("flushes when the browser comes back online", async () => {
    const store = await seeded(1);
    let online = false;
    const { fetchImpl, spy } = api();
    const sync = new SyncManager({ apiUrl: "https://api.test", store, fetchImpl, isOnline: () => online });
    const stop = sync.start(60_000);
    await vi.waitFor(() => expect(sync.current.state).toBe("offline"));
    online = true;
    window.dispatchEvent(new Event("online"));
    await vi.waitFor(async () => expect(await store.pendingCount()).toBe(0));
    expect(spy).toHaveBeenCalledTimes(1);
    stop();
  });
});
