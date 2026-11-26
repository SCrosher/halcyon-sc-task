import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgentApi, ApiError, asApiError, isAbort } from "../lib/api";
import { resolveApiUrl, resolveToken, type Settings } from "../lib/settings";
import { finished, newTurn, sleep, withArrival, type Turn, type TurnStatus } from "../lib/turns";
import { Typewriter } from "../lib/typewriter";
import type { Conversation, Message, PostMessageBody, ToolSource } from "../lib/types";
import { uuid } from "../lib/uuid";
import { useActivityLog } from "./useActivityLog";
import { useMemories } from "./useMemories";

const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 5 * 60_000;
const MAX_POLL_FAILURES = 5;

export interface ChatItem extends Message {
  turnId?: string;
  delivery?: "sending" | "failed";
  error?: ApiError;
  /** Arrived during this session (animate in); history loads are static. */
  live?: boolean;
  /** Replaced a streamed draft that was already on screen, so it needs no entrance animation. */
  fromDraft?: boolean;
}

function withFlags(next: ChatItem, prev: ChatItem | undefined): ChatItem {
  return { ...next, live: next.live || prev?.live, fromDraft: next.fromDraft || prev?.fromDraft };
}

export interface ActiveTool {
  toolUseId: string;
  name: string;
  source?: ToolSource;
}

/** Callbacks a transport (stream or poll) uses to report a turn's progress. */
interface TurnTracker {
  turn: Turn;
  body: PostMessageBody;
  signal: AbortSignal;
  markDelivered: () => void;
  isDelivered: () => boolean;
  recordAssistant: (id: string) => void;
  finish: (status: TurnStatus, error?: string) => void;
}

export function useAgentChat(settings: Settings) {
  const { memberId, memberName, conversationId, streaming } = settings;
  const apiBaseUrl = resolveApiUrl(settings);
  const token = resolveToken(settings);
  const connected = token.trim().length > 0;
  const api = useMemo(() => new AgentApi({ baseUrl: apiBaseUrl, token }), [apiBaseUrl, token]);

  const { memories, refresh: refreshMemories } = useMemories(api, memberId, connected);
  const { activity, log, logError, finishTool, clear: clearActivity } = useActivityLog();

  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<ActiveTool | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [historyError, setHistoryError] = useState<ApiError | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const itemsRef = useRef(items);
  itemsRef.current = items;
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const turnByMessage = useRef(new Map<string, string>());
  const liveIds = useRef(new Set<string>());
  const sessionRef = useRef<AbortController>(new AbortController());

  const patchTurn = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const upsertMessage = useCallback((m: Message, opts: { replaceId?: string; fromDraft?: boolean } = {}) => {
    const { replaceId, fromDraft } = opts;
    const turnId = turnByMessage.current.get(m.id) ?? (replaceId ? turnByMessage.current.get(replaceId) : undefined);
    if (turnId) turnByMessage.current.set(m.id, turnId);
    liveIds.current.add(m.id);
    setItems((xs) => {
      const idx = xs.findIndex((x) => x.id === m.id || (replaceId !== undefined && x.id === replaceId));
      const next: ChatItem = { ...m, turnId, live: true, fromDraft };
      if (idx < 0) return [...xs, next];
      const copy = xs.slice();
      // Keep the same React key when the server echoes our optimistic message, so it doesn't re-mount.
      copy[idx] = withFlags(next, copy[idx]);
      return copy;
    });
  }, []);

  /** Server list is authoritative; keep local-only items (sending / failed) at the end. */
  const mergeServer = useCallback((server: Message[]) => {
    setItems((xs) => {
      const ids = new Set(server.map((m) => m.id));
      const prev = new Map(xs.map((x) => [x.id, x]));
      const merged: ChatItem[] = server.map((m) =>
        withFlags({ ...m, turnId: turnByMessage.current.get(m.id), live: liveIds.current.has(m.id) }, prev.get(m.id)),
      );
      for (const x of xs) if (x.delivery && !ids.has(x.id)) merged.push(x);
      return merged;
    });
  }, []);

  // Reload the conversation whenever the connection, member or conversation changes.
  useEffect(() => {
    sessionRef.current.abort();
    const ctrl = new AbortController();
    sessionRef.current = ctrl;
    const { signal } = ctrl;

    turnByMessage.current = new Map();
    liveIds.current = new Set();
    setItems([]);
    setDraft(null);
    setActiveTool(null);
    setTurns([]);
    setConversation(null);
    setHistoryError(null);
    setBusy(false);

    if (!connected) {
      setHistoryError(new ApiError(401, "Add a bearer token in Settings to connect."));
      return () => ctrl.abort();
    }

    setHistoryLoading(true);
    (async () => {
      try {
        const [msgs, conv] = await Promise.all([
          api.getMessages(conversationId, signal),
          api.getConversation(conversationId, signal),
        ]);
        setItems(msgs);
        setConversation(conv);
      } catch (e) {
        if (isAbort(e)) return;
        const err = asApiError(e);
        // 404 simply means a fresh conversation that the first message will create.
        if (err.status !== 404) setHistoryError(err);
      } finally {
        if (!signal.aborted) setHistoryLoading(false);
      }
    })();

    return () => ctrl.abort();
  }, [api, connected, conversationId, memberId]);

  /** Streamed delivery: apply SSE events as they arrive, until turn.completed. */
  const streamTurn = useCallback(
    async (t: TurnTracker) => {
      const { turn, signal } = t;
      let completed = false;
      let draftText = "";
      const typewriter = new Typewriter(setDraft);
      const discardDraft = () => {
        draftText = "";
        typewriter.reset();
        setDraft(null);
      };
      try {
        for await (const ev of api.streamMessage(conversationId, t.body, signal)) {
          if (!t.isDelivered()) t.markDelivered();
          switch (ev.event) {
            case "message.created": {
              const m = ev.data;
              if (m.role === "member") {
                upsertMessage(m, { replaceId: turn.messageId });
                break;
              }
              t.recordAssistant(m.id);
              // Let the paced draft finish typing before the final message takes its place.
              if (draftText) await typewriter.drain(signal);
              if (signal.aborted) return;
              upsertMessage(m, { fromDraft: draftText.length > 0 });
              discardDraft();
              break;
            }
            case "reply.delta":
              draftText += ev.data.text;
              typewriter.push(ev.data.text);
              break;
            case "reply.reset":
              discardDraft();
              break;
            case "tool.started":
              setActiveTool({ toolUseId: ev.data.tool_use_id, name: ev.data.name, source: ev.data.source });
              log({
                kind: "tool",
                turnIndex: turn.index,
                toolUseId: ev.data.tool_use_id,
                name: ev.data.name,
                source: ev.data.source,
                status: "running",
              });
              break;
            case "tool.finished": {
              const d = ev.data;
              setActiveTool((a) => (a?.toolUseId === d.tool_use_id ? null : a));
              finishTool({
                toolUseId: d.tool_use_id,
                name: d.name,
                isError: d.is_error,
                durationMs: d.duration_ms,
                turnIndex: turn.index,
              });
              break;
            }
            case "error":
              log({ kind: "error", turnIndex: turn.index, title: "Stream error", detail: ev.data.detail });
              patchTurn(turn.id, (x) => ({ ...x, errors: [...x.errors, ev.data.detail] }));
              break;
            case "turn.completed":
              completed = true;
              t.finish(ev.data.status === "ok" ? "ok" : "error");
              log({ kind: "info", turnIndex: turn.index, text: `Turn ${turn.index} completed · ${ev.data.status}` });
              break;
            default:
              log({ kind: "info", turnIndex: turn.index, text: `Unknown event: ${(ev as { event: string }).event}` });
          }
          if (completed) break;
        }
      } finally {
        typewriter.stop();
      }
      if (!completed) {
        const msg = "Stream closed before turn.completed";
        log({ kind: "error", turnIndex: turn.index, title: "Stream interrupted", detail: msg });
        t.finish("interrupted", msg);
      }
    },
    [api, conversationId, finishTool, log, patchTurn, upsertMessage],
  );

  /** Polled delivery: POST, then poll messages and status until the conversation goes idle. */
  const pollTurn = useCallback(
    async (t: TurnTracker, seen: Set<string>) => {
      const { turn, signal } = t;
      const accepted = await api.postMessage(conversationId, t.body, signal);
      t.markDelivered();
      log({ kind: "info", turnIndex: turn.index, text: `202 · ${accepted.status}` });

      const started = performance.now();
      let sawProcessing = false;
      let idleWithoutProgress = 0;
      let failures = 0;
      while (true) {
        try {
          const [msgs, conv] = await Promise.all([
            api.getMessages(conversationId, signal),
            api.getConversation(conversationId, signal),
          ]);
          failures = 0;
          for (const m of msgs) if (m.role === "assistant") t.recordAssistant(m.id);
          mergeServer(msgs);
          setConversation(conv);
          if (conv.status === "processing") sawProcessing = true;
          // Idle is only final once the turn has visibly started (or a few polls show nothing happening).
          else if (sawProcessing || seen.size > 0 || ++idleWithoutProgress >= 3) break;
        } catch (e) {
          if (isAbort(e)) throw e;
          logError(e, turn.index);
          if (++failures >= MAX_POLL_FAILURES) throw e;
        }
        if (performance.now() - started > POLL_TIMEOUT_MS) {
          const msg = "Gave up polling after 5 minutes; conversation still processing";
          log({ kind: "error", turnIndex: turn.index, title: "Polling timed out", detail: msg });
          t.finish("interrupted", msg);
          return;
        }
        await sleep(POLL_INTERVAL_MS, signal);
      }
      t.finish("ok");
      log({ kind: "info", turnIndex: turn.index, text: `Turn ${turn.index} completed · idle` });
    },
    [api, conversationId, log, logError, mergeServer],
  );

  const runTurn = useCallback(
    async (messageId: string, text: string, opts: { retryOf?: string } = {}) => {
      const signal = sessionRef.current.signal;
      const turn = newTurn(uuid(), turnsRef.current.length + 1, messageId, text, streaming ? "stream" : "poll");
      const known = new Set(itemsRef.current.map((i) => i.id));
      const seen = new Set<string>();
      turnByMessage.current.set(messageId, turn.id);

      setTurns((ts) => [...ts, turn]);
      setItems((xs) => {
        const local: ChatItem = {
          id: messageId,
          role: "member",
          text,
          created_at: new Date().toISOString(),
          delivery: "sending",
          live: true,
          turnId: turn.id,
        };
        const idx = opts.retryOf ? xs.findIndex((x) => x.id === opts.retryOf) : -1;
        if (idx < 0) return [...xs, local];
        const copy = xs.slice();
        copy[idx] = local;
        return copy;
      });
      setBusy(true);
      const modeLabel = turn.mode === "stream" ? "streaming" : "polling";
      log({ kind: "info", turnIndex: turn.index, text: `Turn ${turn.index} sent · ${modeLabel}` });

      let delivered = false;
      const tracker: TurnTracker = {
        turn,
        body: { message_id: messageId, member: { id: memberId, name: memberName }, text },
        signal,
        isDelivered: () => delivered,
        markDelivered: () => {
          delivered = true;
          setItems((xs) =>
            xs.map((x) => (x.id === messageId && x.delivery ? { ...x, delivery: undefined, error: undefined } : x)),
          );
        },
        recordAssistant: (id) => {
          if (seen.has(id) || known.has(id)) return;
          seen.add(id);
          liveIds.current.add(id);
          turnByMessage.current.set(id, turn.id);
          const at = performance.now();
          patchTurn(turn.id, (x) => withArrival(x, id, at));
        },
        finish: (status, error) => patchTurn(turn.id, (x) => finished(x, status, error)),
      };

      try {
        if (turn.mode === "stream") await streamTurn(tracker);
        else await pollTurn(tracker, seen);
      } catch (e) {
        if (isAbort(e)) return;
        const err = asApiError(e);
        logError(err, turn.index);
        if (!delivered) {
          // The send itself was rejected; the error shows on the member's bubble with a retry.
          setItems((xs) => xs.map((x) => (x.id === messageId ? { ...x, delivery: "failed", error: err } : x)));
          tracker.finish("error");
        } else {
          tracker.finish("error", `${err.title}: ${err.detail}`);
        }
      } finally {
        if (!signal.aborted) {
          setBusy(false);
          setDraft(null);
          setActiveTool(null);
          void refreshMemories();
          api
            .getConversation(conversationId, signal)
            .then(setConversation)
            .catch(() => {});
        }
      }
    },
    [
      api,
      conversationId,
      log,
      logError,
      memberId,
      memberName,
      patchTurn,
      pollTurn,
      refreshMemories,
      streamTurn,
      streaming,
    ],
  );

  const send = useCallback(
    (text: string) => {
      const t = text.trim();
      if (!t || busy) return;
      void runTurn(uuid(), t);
    },
    [busy, runTurn],
  );

  /** Retry a failed send with the same message_id (exercises idempotency). */
  const retry = useCallback(
    (messageId: string) => {
      const item = itemsRef.current.find((x) => x.id === messageId);
      if (!item || busy) return;
      void runTurn(messageId, item.text, { retryOf: messageId });
    },
    [busy, runTurn],
  );

  /** Re-POST a delivered message with its original message_id; expect status "duplicate". */
  const resendDuplicate = useCallback(
    async (messageId: string) => {
      const item = itemsRef.current.find((x) => x.id === messageId);
      if (!item) return;
      try {
        const r = await api.postMessage(
          conversationId,
          { message_id: messageId, member: { id: memberId, name: memberName }, text: item.text },
          sessionRef.current.signal,
        );
        log({ kind: "info", text: `Resent ${messageId.slice(0, 8)} · 202 ${r.status}` });
      } catch (e) {
        if (!isAbort(e)) logError(e);
      }
    },
    [api, conversationId, log, logError, memberId, memberName],
  );

  return {
    items,
    draft,
    activeTool,
    turns,
    activity,
    conversation,
    historyError,
    historyLoading,
    busy,
    memories,
    send,
    retry,
    resendDuplicate,
    refreshMemories,
    clearActivity,
  };
}

export type AgentChat = ReturnType<typeof useAgentChat>;
