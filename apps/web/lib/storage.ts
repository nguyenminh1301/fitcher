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
