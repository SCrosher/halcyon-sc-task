import { describe, expect, it } from "vitest";
import { readSse } from "./sse";

function body(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const events = [];
  for await (const e of readSse(stream)) events.push(e);
  return events;
}

describe("readSse", () => {
  it("parses events split across chunks", async () => {
    const events = await collect(
      body('event: message.created\ndata: {"id"', ':"m1"}\n\nevent: turn.completed\n', "data: {}\n\n"),
    );
    expect(events).toEqual([
      { event: "message.created", data: '{"id":"m1"}' },
      { event: "turn.completed", data: "{}" },
    ]);
  });

  it("handles CRLF, comments and multi-line data", async () => {
    const events = await collect(body(": keepalive\r\n\r\nevent: x\r\ndata: one\r\ndata: two\r\n\r\n"));
    expect(events).toEqual([{ event: "x", data: "one\ntwo" }]);
  });

  it("defaults the event name and flushes a final event without a blank line", async () => {
    expect(await collect(body("data: hello\n"))).toEqual([{ event: "message", data: "hello" }]);
    // A line cut off mid-way is dropped, as the SSE spec requires.
    expect(await collect(body("data: hel"))).toEqual([]);
  });
});
