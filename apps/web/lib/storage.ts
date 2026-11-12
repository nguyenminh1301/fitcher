// Per-browser preferences (language, theme, demo conversations). Storage can be missing or throw
// (private windows, blocked site data), so every access falls back to "nothing stored".

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Not stored: the preference lasts until the page reloads.
  }
}

/** Whether browser storage works here (it can be missing or blocked). */
export function storageAvailable(): boolean {
  try {
    window.localStorage.setItem("fitcher.storage-check", "1");
    window.localStorage.removeItem("fitcher.storage-check");
    return true;
  } catch {
    return false;
  }
}
