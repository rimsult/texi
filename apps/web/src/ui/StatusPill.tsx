import { useT } from "../i18n";
import type { SyncStatus } from "../services/sync";

interface Props {
  online: boolean;
  sync: SyncStatus;
  offlineReady: boolean;
  /** false: the browser refused local storage, progress lives until the tab closes. */
  persistent?: boolean;
}

export function StatusPill({ online, sync, offlineReady, persistent = true }: Props) {
  const t = useT().status;
  let tone = "ok";
  let text: string;
  if (!persistent) {
    tone = "warn";
    text = t.volatile;
  } else if (sync.state === "disabled") {
    // No server configured (e.g. the single-file build): the network does not matter.
    text = t.local;
  } else if (!online) {
    tone = "warn";
    text = sync.pending ? t.offlineQueued(sync.pending) : t.offline;
  } else if (sync.state === "syncing") {
    text = t.syncing;
  } else if (sync.state === "error") {
    tone = "warn";
    text = t.serverDown(sync.pending);
  } else {
    text = sync.pending ? t.queued(sync.pending) : t.synced;
  }
  return (
    <div className="status" role="status" aria-live="polite" title={offlineReady ? t.savedOnDevice : undefined}
      data-offline-ready={offlineReady || undefined}>
      <span className={`status__dot status__dot--${tone}`} aria-hidden />
      <span data-testid="sync-status">{text}</span>
    </div>
  );
}
