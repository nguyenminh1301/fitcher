// A question picked outside the chat (the setup's suggested questions after the first pack is built), kept for the
// browser tab until the chat asks it. Storage can be unavailable (a private window, blocked site data); then the
// chat simply opens without asking.

const KEY = "fitcher.pendingQuestion";

export function keepQuestion(question: string): void {
  try {
    sessionStorage.setItem(KEY, question);
  } catch {
    // The chat opens without the question.
  }
}

/** The kept question, removed so it is asked once. */
export function takeQuestion(): string | null {
  try {
    const question = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return question;
  } catch {
    return null;
  }
}
