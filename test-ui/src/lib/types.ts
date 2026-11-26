// Wire types — mirror agent-api/app/schemas.py and the SSE contract.

export type Role = "member" | "assistant";

export interface Message {
  id: string;
  role: Role;
  text: string;
  created_at: string;
}

export interface Member {
  id: string;
  name: string;
}

export interface PostMessageBody {
  message_id: string;
  member: Member;
  text: string;
}

export interface Accepted {
  message_id: string;
  conversation_id: string;
  status: "accepted" | "duplicate";
}

export interface Conversation {
  id: string;
  member_id: string;
  status: "processing" | "idle";
  created_at: string;
  updated_at: string;
}

export interface Memory {
  id: string;
  category: string;
  content: string;
  updated_at: string;
}

export type ToolSource = "memory" | "calendar" | "restaurants";

export type StreamEvent =
  | { event: "message.created"; data: Message }
  | { event: "reply.delta"; data: { text: string } }
  /** Discard the unposted draft: the model call is being re-issued. */
  | { event: "reply.reset"; data: Record<string, never> }
  | { event: "tool.started"; data: { tool_use_id: string; name: string; source: ToolSource } }
  | { event: "tool.finished"; data: { tool_use_id: string; name: string; is_error: boolean; duration_ms: number } }
  | { event: "turn.completed"; data: { status: "ok" | "error" } }
  | { event: "error"; data: { detail: string } };
