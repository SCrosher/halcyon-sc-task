import { readSse } from "./sse";
import type { Accepted, Conversation, Memory, Message, PostMessageBody, StreamEvent } from "./types";

export interface ApiConfig {
  baseUrl: string;
  token: string;
}

/** `status` for an error that never reached the network (a bug or unexpected exception). */
export const UNEXPECTED = -1;

export class ApiError extends Error {
  /** HTTP status; 0 when the request could not be sent, UNEXPECTED for anything else. */
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  get title(): string {
    switch (this.status) {
      case UNEXPECTED:
        return "Unexpected error";
      case 0:
        return "Unable to reach the agent API";
      case 401:
        return "Not authorised";
      case 404:
        return "Not found";
      case 409:
        return "Conversation belongs to another member";
      case 422:
        return "Request rejected";
      default:
        return this.status >= 500 ? `Server error · ${this.status}` : `Request failed · ${this.status}`;
    }
  }

  /** Member-facing wording, with no status codes or internals. */
  get friendly(): string {
    switch (this.status) {
      case 0:
        return "We can't reach Halcyon at the moment. Please check your connection and try again.";
      case 401:
        return "Halcyon isn't available right now. Please try again later.";
      case 409:
        return "This conversation is no longer available. Please start a new one.";
      case 422:
        return "We couldn't send that message. Please shorten it or rephrase and try again.";
      default:
        return "Something went wrong on our side. Please try again in a moment.";
    }
  }

  get hint(): string | undefined {
    switch (this.status) {
      case 0:
        return "Check the API base URL in Settings, and that the service is running.";
      case 401:
        return "The bearer token is missing or was rejected. Update it in Settings.";
      case 409:
        return "Start a new conversation, or switch back to the member who owns this one.";
      default:
        return undefined;
    }
  }
}

export function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

export function asApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError(UNEXPECTED, e instanceof Error ? e.message : String(e));
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // FastAPI validation errors: [{loc, msg, type}]
      return d
        .map((e: unknown) => {
          if (e && typeof e === "object" && "msg" in e) {
            const { loc, msg } = e as { loc?: unknown; msg: unknown };
            const path = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
            return path ? `${path}: ${String(msg)}` : String(msg);
          }
          return JSON.stringify(e);
        })
        .join("; ");
    }
    return JSON.stringify(d);
  }
  return fallback;
}

async function toApiError(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => "");
  let body: unknown = undefined;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, detailOf(body, text || res.statusText || "No response body"));
}

export class AgentApi {
  private readonly cfg: ApiConfig;

  constructor(cfg: ApiConfig) {
    this.cfg = cfg;
  }

  private url(path: string): string {
    return this.cfg.baseUrl.trim().replace(/\/+$/, "") + path;
  }

  private async send(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.cfg.token}`);
    if (init.body) headers.set("Content-Type", "application/json");
    let res: Response;
    try {
      res = await fetch(this.url(path), { ...init, headers });
    } catch (e) {
      if (isAbort(e)) throw e;
      throw new ApiError(0, e instanceof Error ? e.message : String(e));
    }
    if (!res.ok) throw await toApiError(res);
    return res;
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await this.send(path, init);
    return (await res.json()) as T;
  }

  postMessage(conversationId: string, body: PostMessageBody, signal?: AbortSignal): Promise<Accepted> {
    return this.json(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    });
  }

  async *streamMessage(
    conversationId: string,
    body: PostMessageBody,
    signal?: AbortSignal,
  ): AsyncGenerator<StreamEvent> {
    const res = await this.send(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { Accept: "text/event-stream" },
      signal,
    });
    const type = res.headers.get("content-type") ?? "";
    if (!type.includes("text/event-stream") || !res.body) {
      const text = await res.text().catch(() => "");
      throw new ApiError(
        res.status,
        `Expected an event stream but got ${type || "no content type"}${text ? `: ${text.slice(0, 200)}` : ""}`,
      );
    }
    for await (const raw of readSse(res.body)) {
      let data: unknown;
      try {
        data = JSON.parse(raw.data);
      } catch {
        yield { event: "error", data: { detail: `Malformed ${raw.event} event: ${raw.data.slice(0, 200)}` } };
        continue;
      }
      yield { event: raw.event, data } as StreamEvent;
    }
  }

  async getMessages(conversationId: string, signal?: AbortSignal): Promise<Message[]> {
    const r = await this.json<{ messages: Message[] }>(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        signal,
      },
    );
    return r.messages;
  }

  getConversation(conversationId: string, signal?: AbortSignal): Promise<Conversation> {
    return this.json(`/conversations/${encodeURIComponent(conversationId)}`, { signal });
  }

  async getMemories(memberId: string, signal?: AbortSignal): Promise<Memory[]> {
    const r = await this.json<{ memories: Memory[] }>(`/members/${encodeURIComponent(memberId)}/memories`, { signal });
    return r.memories;
  }
}
