import { isTauri } from "./utils";

export interface AvailableUpdate {
  version: string;
  notes?: string;
  install: () => Promise<void>;
}

/** Ask GitHub Releases for a newer signed desktop build (desktop app only). */
export async function checkForUpdate(): Promise<AvailableUpdate | null> {
  if (!isTauri()) return null;
  const { check } = await import("@tauri-apps/plugin-updater");
  const update = await check();
  if (!update) return null;
  return {
    version: update.version,
    notes: update.body,
    install: async () => {
      await update.downloadAndInstall();
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    },
  };
}
