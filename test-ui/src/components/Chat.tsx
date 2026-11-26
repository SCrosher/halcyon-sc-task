import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import type { AgentChat, ChatItem } from "../hooks/useAgentChat";
import { useDevMode } from "../hooks/useDevMode";
import { LATENCY_LIMIT_MS, formatDuration, formatTime, greeting } from "../lib/format";
import type { Turn } from "../lib/turns";
import type { ToolSource } from "../lib/types";
import { Alert, ArrowUp, Calendar, Dining, Repeat } from "./icons";
import { Emblem } from "./Logo";
import { RevealText, StreamText, Swap, usePresence } from "./motion";
import { Button, cx, Spinner } from "./ui";

const MAX_TEXT = 4000;

// Memory tools are deliberately absent: the agent saves memories silently.
const TOOL_STATUS: Partial<Record<ToolSource, { label: string; Icon: (p: { className?: string }) => ReactNode }>> = {
  calendar: { label: "Checking your diary", Icon: Calendar },
  restaurants: { label: "Considering restaurants for you", Icon: Dining },
};

const SUGGESTIONS = [
  "Could you book dinner for two on Friday evening?",
  "What is in my diary tomorrow?",
  "Please remember I'm allergic to shellfish.",
];

const BUBBLE_WIDTH = "max-w-[min(560px,85%)]";
const ASSISTANT_SURFACE = "border border-line bg-surface text-ink shadow-soft";

/** Corner radii by position in a run of same-sender bubbles: tail corner tightens, joined edges tighten. */
function radius(mine: boolean, start: boolean) {
  return mine
    ? cx("rounded-[22px] rounded-br-[8px]", !start && "rounded-tr-[8px]")
    : cx("rounded-[22px] rounded-bl-[8px]", !start && "rounded-tl-[8px]");
}

export function Chat({
  chat,
  memberName,
  memberId,
  connected,
}: {
  chat: AgentChat;
  memberName: string;
  memberId: string;
  /** False when no bearer token is configured. */
  connected: boolean;
}) {
  const { items, draft, turns, busy, historyError, historyLoading, conversation, activeTool } = chat;
  const { dev } = useDevMode();
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastCount = useRef(0);

  const turnsById = useMemo(() => new Map(turns.map((t) => [t.id, t])), [turns]);
  const rows = useMemo(() => {
    const lastOfTurn = new Map<string, number>();
    items.forEach((it, i) => it.turnId && lastOfTurn.set(it.turnId, i));
    return items.map((it, i) => {
      const turn = it.turnId ? turnsById.get(it.turnId) : undefined;
      const endsTurn = !!turn && lastOfTurn.get(turn.id) === i && turn.status !== "running" && it.delivery !== "failed";
      return { it, turn, endsTurn };
    });
  }, [items, turnsById]);
  const runningTurn = turns.find((t) => t.status === "running");

  // While pinned to the bottom, follow new content: smooth-scroll for new messages, jump while text streams.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !pinned.current) return;
    const grew = items.length > lastCount.current;
    lastCount.current = items.length;
    el.scrollTo({ top: el.scrollHeight, behavior: grew && items.length > 1 ? "smooth" : "auto" });
  }, [items, draft, busy, turns]);

  const foreign = conversation && conversation.member_id !== memberId;
  const empty = !items.length && !historyLoading;
  const welcome = usePresence(empty, 320);
  const lastRole = items[items.length - 1]?.role;
  const lastEndsTurn = rows[rows.length - 1]?.endsTurn;

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 scrollbar-quiet overflow-y-auto"
      >
        <div className="relative mx-auto flex min-h-full w-full max-w-[760px] flex-col justify-end px-4 pt-8 pb-6 sm:px-8 sm:pt-12">
          {historyError &&
            connected &&
            (dev ? (
              <Banner title={historyError.title} detail={historyError.detail} hint={historyError.hint} />
            ) : (
              <Banner title={historyError.friendly} />
            ))}
          {!connected && dev && (
            <Banner title="No bearer token" detail="Add one in Settings to connect to the agent API." />
          )}
          {dev && foreign && (
            <Banner
              title="This conversation belongs to another member"
              detail={`Owner ${conversation.member_id}. Sending as the current member will return 409.`}
            />
          )}

          {historyLoading && (
            <div className="flex flex-1 animate-fade items-center justify-center text-faint">
              <Spinner />
            </div>
          )}

          {welcome.mounted && (
            <EmptyState name={memberName} onPick={chat.send} disabled={busy || !connected} leaving={welcome.leaving} />
          )}

          <ol className="flex flex-col" role="log" aria-live="polite" aria-relevant="additions">
            {rows.map(({ it, turn, endsTurn }, i) => {
              const prev = rows[i - 1];
              const next = rows[i + 1];
              const start = !prev || prev.it.role !== it.role || prev.endsTurn;
              const end = !next || next.it.role !== it.role || endsTurn;
              return [
                <Bubble key={it.id} item={it} start={start} end={end} chat={chat} busy={busy} dev={dev} />,
                endsTurn &&
                  turn &&
                  (dev ? <TurnFooter key={`${it.id}:f`} turn={turn} /> : <TurnNotice key={`${it.id}:f`} turn={turn} />),
              ];
            })}

            {draft !== null && draft.length > 0 && (
              <li
                className={cx(
                  "msg-assistant flex justify-start",
                  lastRole === "assistant" && !lastEndsTurn ? "mt-1" : "mt-6",
                )}
              >
                <div
                  className={cx(
                    BUBBLE_WIDTH,
                    radius(false, lastRole !== "assistant" || !!lastEndsTurn),
                    ASSISTANT_SURFACE,
                    "px-5 py-3.5 text-[15px] leading-relaxed break-words whitespace-pre-wrap",
                  )}
                >
                  <StreamText text={draft} />
                </div>
              </li>
            )}

            {busy && !draft && runningTurn && (
              <Waiting
                turn={runningTurn}
                tool={activeTool?.source}
                dev={dev}
                joined={lastRole === "assistant" && !lastEndsTurn}
              />
            )}
          </ol>
        </div>
      </div>

      <Composer onSend={chat.send} busy={busy} connected={connected} />
    </section>
  );
}

function Banner({ title, detail, hint }: { title: string; detail?: string; hint?: string }) {
  return (
    <div className="mb-8 flex animate-rise gap-3 rounded-2xl border border-danger/15 bg-danger-soft px-5 py-4 text-danger">
      <Alert className="mt-0.5 shrink-0 text-[17px]" />
      <div className="min-w-0 text-[13.5px] leading-relaxed">
        <p className="font-medium">{title}</p>
        {detail && <p className="mt-0.5 break-words text-danger/80">{detail}</p>}
        {hint && <p className="mt-1.5 text-ink-soft">{hint}</p>}
      </div>
    </div>
  );
}

function EmptyState({
  name,
  onPick,
  disabled,
  leaving,
}: {
  name: string;
  onPick: (t: string) => void;
  disabled: boolean;
  leaving: boolean;
}) {
  const first = name.trim().split(/\s+/)[0] || "there";
  let i = 0;
  const n = () => ({ "--i": i++ }) as CSSProperties;
  return (
    <div
      className={cx(
        "flex flex-1 flex-col items-center justify-center pb-16 text-center",
        leaving ? "cascade-out absolute inset-0 px-4" : "cascade",
      )}
    >
      <div style={n()}>
        <Emblem size={52} className="mb-8 rounded-[14px] shadow-soft" />
      </div>
      <p className="eyebrow" style={n()}>
        Private client service
      </p>
      <h1
        style={n()}
        className="mt-5 font-display text-[44px] leading-[1.05] font-medium tracking-[-0.01em] text-ink sm:text-[56px]"
      >
        {greeting()}, {first}.
      </h1>
      <p style={n()} className="mt-4 max-w-sm text-[15px] leading-relaxed text-muted">
        How may we be of assistance today?
      </p>
      <div className="mt-10 flex w-full max-w-md flex-col gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            style={n()}
            disabled={disabled}
            onClick={() => onPick(s)}
            className="press rounded-2xl border border-line bg-surface/60 px-5 py-3.5 text-left text-[14px] text-ink-soft transition-[border-color,background-color,box-shadow,transform] duration-300 ease-[var(--ease-out)] hover:-translate-y-px hover:border-line-strong hover:bg-surface hover:shadow-soft disabled:hover:translate-y-0"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Bubble({
  item,
  start,
  end,
  chat,
  busy,
  dev,
}: {
  item: ChatItem;
  start: boolean;
  end: boolean;
  chat: AgentChat;
  busy: boolean;
  dev: boolean;
}) {
  const mine = item.role === "member";
  const failed = item.delivery === "failed";
  const entrance = item.fromDraft ? "" : item.live ? (mine ? "msg-member" : "msg-assistant") : "history-in";
  const reveal = !mine && item.live && !item.fromDraft;

  return (
    <li
      className={cx(
        "group flex flex-col",
        mine ? "items-end" : "items-start",
        start ? "mt-6 first:mt-0" : "mt-1",
        entrance,
      )}
    >
      <div
        className={cx(
          BUBBLE_WIDTH,
          radius(mine, start),
          "px-5 py-3.5 text-[15px] leading-relaxed break-words whitespace-pre-wrap transition-opacity duration-500 ease-[var(--ease-out)]",
          mine ? "bg-ink text-canvas" : ASSISTANT_SURFACE,
          item.delivery === "sending" && "opacity-70",
          failed && "opacity-45",
        )}
      >
        {reveal ? <RevealText text={item.text} /> : item.text}
      </div>

      {(end || item.delivery) && (
        <div
          className={cx(
            "mt-1.5 flex items-center gap-3 px-1.5 text-[11.5px] text-faint",
            mine && "flex-row-reverse",
            item.live && "meta-in",
          )}
        >
          <time dateTime={item.created_at} title={item.created_at}>
            <Swap id={item.delivery === "sending" ? "sending" : "sent"}>
              {item.delivery === "sending" ? "Sending…" : formatTime(item.created_at)}
            </Swap>
          </time>
          {dev && mine && !item.delivery && (
            <button
              onClick={() => chat.resendDuplicate(item.id)}
              className="inline-flex items-center gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100 hover:text-ink focus-visible:opacity-100"
              title="Re-POST with the same message_id. Expect status “duplicate”."
            >
              <Repeat className="text-[12px]" /> Resend same ID
            </button>
          )}
        </div>
      )}

      {failed && item.error && !dev && (
        <div className="notice-in mt-2 flex items-center gap-3 px-1.5 text-[12.5px] text-danger">
          <span>{item.error.friendly}</span>
          <button
            disabled={busy}
            onClick={() => chat.retry(item.id)}
            className="shrink-0 font-medium text-ink underline decoration-line-strong underline-offset-4 transition-colors hover:decoration-ink disabled:opacity-40"
          >
            Try again
          </button>
        </div>
      )}
      {failed && item.error && dev && (
        <div className="notice-in mt-2 flex max-w-[min(560px,85%)] items-start gap-3 rounded-2xl border border-danger/15 bg-danger-soft px-4 py-3 text-[13px] text-danger">
          <Alert className="mt-0.5 shrink-0 text-[15px]" />
          <div className="min-w-0">
            <p className="font-medium">
              {item.error.status > 0 && <span className="tabular-nums">{item.error.status} · </span>}
              {item.error.title}
            </p>
            <p className="mt-0.5 break-words text-danger/80">{item.error.detail}</p>
            {item.error.hint && <p className="mt-1 text-ink-soft">{item.error.hint}</p>}
            <Button
              variant="secondary"
              className="press mt-3 h-8 px-3.5 text-[12.5px]"
              disabled={busy}
              onClick={() => chat.retry(item.id)}
            >
              Retry with same message ID
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function Metric({ label, ms }: { label: string; ms?: number }) {
  const over = ms !== undefined && ms > LATENCY_LIMIT_MS;
  return (
    <span className={cx("tabular-nums", over ? "font-medium text-danger" : "text-muted")}>
      <span className={over ? "text-danger/70" : "text-faint"}>{label}</span> {formatDuration(ms)}
    </span>
  );
}

function TurnFooter({ turn }: { turn: Turn }) {
  return (
    <li className="meta-in mt-2 mb-1 flex flex-col items-start gap-2 px-1.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px]">
        <Metric label="First" ms={turn.firstMs} />
        <Metric label="Final" ms={turn.finalMs} />
        <Metric label="Longest gap" ms={turn.maxGapMs} />
        <span className="text-faint">{turn.mode === "stream" ? "Streamed" : "Polled"}</span>
        {turn.status !== "ok" && <span className="font-medium text-danger capitalize">{turn.status}</span>}
      </div>
      {turn.errors.map((e, i) => (
        <p key={i} className="flex items-start gap-2 text-[12.5px] text-danger">
          <Alert className="mt-0.5 shrink-0" /> <span className="break-words">{e}</span>
        </p>
      ))}
    </li>
  );
}

/** Member-facing note when a delivered turn didn't finish cleanly. */
function TurnNotice({ turn }: { turn: Turn }) {
  if (turn.status === "ok") return null;
  return (
    <li className="notice-in mt-2 px-1.5 text-[12.5px] text-muted">
      This reply was interrupted. Please send your message again.
    </li>
  );
}

/**
 * Typing indicator while a turn runs, labelled with the member-facing tool in use (if any).
 * Developer mode adds a silence timer that turns red past LATENCY_LIMIT_MS.
 */
function Waiting({ turn, tool, dev, joined }: { turn: Turn; tool?: ToolSource; dev: boolean; joined: boolean }) {
  const [now, setNow] = useState(() => performance.now());
  const hadTool = useRef(false);
  const toolStatus = tool ? TOOL_STATUS[tool] : undefined;
  if (toolStatus) hadTool.current = true;

  useEffect(() => {
    if (!dev) return;
    const id = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(id);
  }, [dev]);

  const status = toolStatus ?? (hadTool.current ? { label: "Preparing your reply", Icon: undefined } : undefined);
  const since = turn.arrivals.length ? turn.arrivals[turn.arrivals.length - 1] : turn.t0;
  const silent = Math.max(0, now - since);
  const over = silent > LATENCY_LIMIT_MS;

  return (
    <li className={cx("typing flex items-center gap-4", joined ? "mt-1" : "mt-6")}>
      <div className={cx("flex h-12 items-center gap-[5px] px-5", radius(false, !joined), ASSISTANT_SURFACE)}>
        <span className="typing-dot size-[6px] rounded-full bg-ink" />
        <span className="typing-dot size-[6px] rounded-full bg-ink" />
        <span className="typing-dot size-[6px] rounded-full bg-ink" />
      </div>

      <div className="flex min-w-0 flex-col gap-0.5 text-[12.5px] leading-snug">
        {status && (
          <Swap id={status.label} className="min-w-0">
            <span className="inline-flex items-center gap-2">
              {status.Icon && <status.Icon className="shrink-0 text-[14px] text-accent" />}
              <span className="sheen truncate">{status.label}…</span>
            </span>
          </Swap>
        )}
        {dev && (
          <span className={cx("text-[11.5px] tabular-nums", over ? "font-medium text-danger" : "text-faint")}>
            {turn.arrivals.length ? "Silent for" : "Waiting"} {(silent / 1000).toFixed(1)} s
          </span>
        )}
      </div>
    </li>
  );
}

function Composer({ onSend, busy, connected }: { onSend: (t: string) => void; busy: boolean; connected: boolean }) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  const tooLong = text.length > MAX_TEXT;
  const canSend = connected && !busy && text.trim().length > 0 && !tooLong;
  const submit = () => {
    if (!canSend) return;
    onSend(text);
    setText("");
    ref.current?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="px-4 pb-5 sm:px-8 sm:pb-7">
      <div className="mx-auto w-full max-w-[760px]">
        <div className="flex items-end gap-2 rounded-[26px] border border-line bg-surface p-2 pl-5 shadow-soft transition-[border-color,box-shadow] duration-300 ease-[var(--ease-out)] focus-within:border-line-strong focus-within:shadow-lift">
          <textarea
            ref={ref}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            aria-label="Message"
            placeholder={busy ? "Halcyon is attending to your request…" : "Write a message"}
            className="max-h-[220px] min-h-[40px] flex-1 resize-none scrollbar-quiet bg-transparent py-2.5 text-[15px] leading-relaxed text-ink placeholder:text-faint placeholder:transition-opacity focus:outline-none"
          />
          <button
            onClick={submit}
            disabled={!canSend}
            aria-label="Send"
            className={cx(
              "press mb-0.5 inline-flex size-10 shrink-0 items-center justify-center rounded-full text-[17px]",
              canSend ? "bg-ink text-canvas hover:bg-ink-soft" : "bg-sunken text-faint",
            )}
          >
            <Swap id={busy ? "busy" : "idle"}>{busy ? <Spinner /> : <ArrowUp />}</Swap>
          </button>
        </div>
        <div className="mt-2 flex justify-between px-5 text-[11px] text-faint">
          {connected ? <span>Enter to send · Shift + Enter for a new line</span> : <span>Not connected</span>}
          {text.length > MAX_TEXT - 500 && (
            <span className={cx("tabular-nums", tooLong && "font-medium text-danger")}>
              {text.length.toLocaleString()} / {MAX_TEXT.toLocaleString()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
