// The data source a new conversation is answered from, kept for the browser tab so a choice made in the console
// (the Sources page's "Ask") reaches the chat, which has its own state. Storage can be unavailable (a private
// window, blocked site data); then a new conversation uses the pack used last.

const KEY = "fitcher.chosenPack";

export function readChosenPack(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function keepChosenPack(name: string | null): void {
  try {
    if (name) sessionStorage.setItem(KEY, name);
    else sessionStorage.removeItem(KEY);
  } catch {
    // The choice holds for this page only.
  }
}
