export interface RawSseEvent {
  event: string;
  data: string;
}

/**
 * Minimal SSE parser over a fetch body (EventSource can't POST or send headers).
 * Handles \n and \r\n line endings, multi-line data, and ignores `:` comments (keepalives).
 */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<RawSseEvent> {
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

      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        let line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);

        if (line === "") {
          if (data.length) yield { event: event || "message", data: data.join("\n") };
          event = "";
          data = [];
          continue;
        }
        if (line.startsWith(":")) continue;

        const colon = line.indexOf(":");
        const field = colon < 0 ? line : line.slice(0, colon);
        let val = colon < 0 ? "" : line.slice(colon + 1);
        if (val.startsWith(" ")) val = val.slice(1);

        if (field === "event") event = val;
        else if (field === "data") data.push(val);
      }
    }
    if (data.length) yield { event: event || "message", data: data.join("\n") };
  } finally {
    reader.cancel().catch(() => {});
  }
}
