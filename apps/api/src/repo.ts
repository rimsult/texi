import type { AttemptEventInput } from "./schemas";

export interface SyncResult {
  accepted: string[];
  duplicates: string[];
}

/** What `/v1/sync` returns: invalid events are reported so the client can drop them. */
export interface SyncResponse extends SyncResult {
  rejected: string[];
}

export interface DeviceSummary {
  events: number;
  correct: number;
  words: number;
  lastAnsweredAt: string | null;
}

export interface ReviewItem {
  id: string;
  trainer: string;
  entryId: string;
  lemma: string;
  level: string;
  deck: string;
  lang: string;
  reasons: string[];
}

export interface Repository {
  health(): Promise<boolean>;
  saveEvents(deviceId: string, events: AttemptEventInput[]): Promise<SyncResult>;
  deviceSummary(deviceId: string): Promise<DeviceSummary | null>;
  /** Content as served to clients (same shape as the static packs). */
  manifest(): Promise<unknown | null>;
  pack(level: string, deck?: string): Promise<unknown | null>;
  reviewQueue(level: string | undefined, limit: number): Promise<ReviewItem[]>;
  close(): Promise<void>;
}
