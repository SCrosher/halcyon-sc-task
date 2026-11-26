import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentApi, ApiError, UNEXPECTED, asApiError } from "./api";

const api = new AgentApi({ baseUrl: "http://api.test/", token: "secret" });
const body = { message_id: "m1", member: { id: "u1", name: "Jane" }, text: "hi" };

function mockFetch(response: Response | Error) {
  const fetchMock = vi.fn<typeof fetch>(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function drain(events: AsyncIterable<unknown>) {
  for await (const e of events) void e;
}

afterEach(() => vi.unstubAllGlobals());

describe("AgentApi", () => {
  it("sends the bearer token to a normalised URL", async () => {
    const fetchMock = mockFetch(Response.json({ message_id: "m1", conversation_id: "c 1", status: "accepted" }));
    await api.postMessage("c 1", body);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/conversations/c%201/messages");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer secret");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("turns HTTP errors into ApiErrors with the server's detail", async () => {
    mockFetch(Response.json({ detail: "Missing or invalid bearer token" }, { status: 401 }));
    const error = await api.getMessages("c1").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
    expect(error.detail).toBe("Missing or invalid bearer token");
    expect(error.title).toBe("Not authorised");
  });

  it("flattens FastAPI validation errors", async () => {
    const detail = [{ loc: ["body", "member", "id"], msg: "Field required", type: "missing" }];
    mockFetch(Response.json({ detail }, { status: 422 }));
    const error = await api.postMessage("c1", body).catch((e) => e);
    expect(error.detail).toBe("member.id: Field required");
  });

  it("reports network failures as status 0", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    const error = await api.getConversation("c1").catch((e) => e);
    expect(error.status).toBe(0);
    expect(error.title).toBe("Unable to reach the agent API");
  });

  it("streams parsed events and reports malformed ones", async () => {
    const sse = 'event: reply.delta\ndata: {"text":"Hi"}\n\nevent: reply.delta\ndata: {oops\n\n';
    mockFetch(new Response(sse, { headers: { "Content-Type": "text/event-stream" } }));
    const events = [];
    for await (const e of api.streamMessage("c1", body)) events.push(e);
    expect(events[0]).toEqual({ event: "reply.delta", data: { text: "Hi" } });
    expect(events[1].event).toBe("error");
  });

  it("rejects a non-stream response to a stream request", async () => {
    mockFetch(Response.json({ status: "duplicate" }, { status: 202 }));
    await expect(drain(api.streamMessage("c1", body))).rejects.toThrow(/Expected an event stream/);
  });
});

describe("asApiError", () => {
  it("labels unexpected errors without a fake status code", () => {
    const error = asApiError(new Error("boom"));
    expect(error.status).toBe(UNEXPECTED);
    expect(error.title).toBe("Unexpected error");
    expect(error.detail).toBe("boom");
  });

  it("passes ApiErrors through", () => {
    const original = new ApiError(409, "taken");
    expect(asApiError(original)).toBe(original);
  });
});
