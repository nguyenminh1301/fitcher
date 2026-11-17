// The text shown for a failed api call: the api's own reason without the "The api answered <status>:" prefix that
// the http clients put in front of it for logs and tests, or the status alone when the api gave no reason.

const PREFIX = /^The api answered \d+: /;

export function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message.replace(PREFIX, "") : String(cause);
}
