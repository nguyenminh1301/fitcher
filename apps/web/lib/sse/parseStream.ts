// Read a server-sent event stream (text/event-stream) from a fetch body. Browsers' EventSource only
// supports GET, and /ask is a POST, so the frames are parsed here: `event:` names a frame, `data:` lines
// are joined with newlines, a blank line ends the frame and lines starting with `:` are comments.

export type SseFrame = { event: string; data: string };

export async function* parseStream(body: ReadableStream<Uint8Array>): AsyncGenerator<SseFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  let data: string[] = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = buffer.search(/\r\n|\r|\n/)) >= 0) {
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + (buffer.startsWith("\r\n", end) ? 2 : 1));
        if (line === "") {
          if (data.length) yield { event: event || "message", data: data.join("\n") };
          event = "";
          data = [];
          continue;
        }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        const text = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = text;
        else if (field === "data") data.push(text);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
