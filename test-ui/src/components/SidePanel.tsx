import { useMemo, useState, type ReactNode } from "react";
import type { Activity } from "../hooks/useActivityLog";
import type { AgentChat } from "../hooks/useAgentChat";
import type { Turn } from "../lib/turns";
import { LATENCY_LIMIT_MS, formatDuration, formatRelative, formatTime } from "../lib/format";
import type { ToolSource } from "../lib/types";
import { Alert, Calendar, Check, Dining, Memory, Refresh } from "./icons";
import { cx, IconButton, Spinner } from "./ui";

type Tab = "latency" | "activity" | "memories";

const TAB_KEY = "halcyon:dev-tab";

function loadTab(): Tab {
  try {
    const t = localStorage.getItem(TAB_KEY);
    if (t === "latency" || t === "activity" || t === "memories") return t;
  } catch {
    /* ignore */
  }
  return "latency";
}

export function SidePanel({ chat }: { chat: AgentChat }) {
  const [tab, setTabState] = useState<Tab>(loadTab);
  const setTab = (t: Tab) => {
    setTabState(t);
    try {
      localStorage.setItem(TAB_KEY, t);
    } catch {
      /* ignore */
    }
  };
  const breaches = chat.turns.filter(isBreach).length;
  const errors = chat.activity.filter((a) => a.kind === "error" || (a.kind === "tool" && a.status === "error")).length;

  const tabs: { id: Tab; label: string; badge?: ReactNode }[] = [
    { id: "latency", label: "Latency", badge: breaches ? <Badge tone="danger">{breaches}</Badge> : undefined },
    { id: "activity", label: "Activity", badge: errors ? <Badge tone="danger">{errors}</Badge> : undefined },
    {
      id: "memories",
      label: "Memories",
      badge: chat.memories.items.length ? <Badge>{chat.memories.items.length}</Badge> : undefined,
    },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div role="tablist" className="flex gap-6 border-b border-line px-6">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cx(
              "relative -mb-px flex h-14 items-center gap-2 border-b text-[13px] transition-colors duration-150",
              tab === t.id ? "border-ink font-medium text-ink" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {t.label}
            {t.badge}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 scrollbar-quiet overflow-y-auto">
        {tab === "latency" && <LatencyPanel turns={chat.turns} />}
        {tab === "activity" && <ActivityPanel activity={chat.activity} onClear={chat.clearActivity} />}
        {tab === "memories" && <MemoriesPanel chat={chat} />}
      </div>
    </div>
  );
}

function Badge({ children, tone }: { children: ReactNode; tone?: "danger" }) {
  return (
    <span
      className={cx(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[10.5px] font-medium tabular-nums",
        tone === "danger" ? "bg-danger-soft text-danger" : "bg-sunken text-muted",
      )}
    >
      {children}
    </span>
  );
}

function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="px-6 py-16 text-center">
      <p className="font-display text-[22px] text-ink">{title}</p>
      <p className="mx-auto mt-2 max-w-[260px] text-[13px] leading-relaxed text-muted">{children}</p>
    </div>
  );
}

function isBreach(t: Turn): boolean {
  return [t.firstMs, t.finalMs, t.maxGapMs].some((v) => v !== undefined && v > LATENCY_LIMIT_MS);
}

function percentile(xs: number[], p: number): number | undefined {
  if (!xs.length) return undefined;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil((p / 100) * s.length) - 1)];
}

function Ms({ ms, strong }: { ms?: number; strong?: boolean }) {
  const over = ms !== undefined && ms > LATENCY_LIMIT_MS;
  return (
    <span className={cx("tabular-nums", over ? "font-medium text-danger" : strong ? "text-ink" : "text-ink-soft")}>
      {formatDuration(ms)}
    </span>
  );
}

function LatencyPanel({ turns }: { turns: Turn[] }) {
  const stats = useMemo(() => {
    const first = turns.flatMap((t) => (t.firstMs !== undefined ? [t.firstMs] : []));
    const gaps = turns.flatMap((t) => (t.maxGapMs !== undefined ? [t.maxGapMs] : []));
    return {
      p50: percentile(first, 50),
      p95: percentile(first, 95),
      worstGap: gaps.length ? Math.max(...gaps) : undefined,
      breaches: turns.filter(isBreach).length,
    };
  }, [turns]);

  if (!turns.length)
    return (
      <Empty title="No turns yet">
        Each turn records time to the first assistant message, to the final message, and the longest silence between
        messages. Anything over 12 s is shown in red.
      </Empty>
    );

  return (
    <div className="px-6 py-6">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-line bg-line">
        <Stat label="First reply · p50" value={<Ms ms={stats.p50} strong />} />
        <Stat label="First reply · p95" value={<Ms ms={stats.p95} strong />} />
        <Stat label="Longest silence" value={<Ms ms={stats.worstGap} strong />} />
        <Stat
          label="Over 12 s"
          value={
            <span className={cx("tabular-nums", stats.breaches ? "text-danger" : "text-ok")}>
              {stats.breaches} <span className="text-[13px] text-muted">of {turns.length}</span>
            </span>
          }
        />
      </div>

      <p className="mt-8 mb-3 eyebrow">Turns</p>
      <ol className="flex flex-col">
        {[...turns].reverse().map((t) => (
          <li key={t.id} className="border-b border-line py-4 last:border-0">
            <div className="flex items-baseline justify-between gap-3">
              <p className="min-w-0 truncate text-[13.5px] text-ink" title={t.text}>
                <span className="mr-2 text-faint tabular-nums">{t.index}</span>
                {t.text}
              </p>
              <span className="shrink-0 text-[11.5px] text-faint">{formatTime(t.startedAt, true)}</span>
            </div>
            <div className="mt-2.5 grid grid-cols-3 gap-3 text-[12.5px]">
              <Cell label="First">
                <Ms ms={t.firstMs} />
              </Cell>
              <Cell label="Final">
                <Ms ms={t.finalMs} />
              </Cell>
              <Cell label="Longest gap">
                <Ms ms={t.maxGapMs} />
              </Cell>
            </div>
            <div className="mt-2.5 flex items-center gap-3 text-[11.5px] text-faint">
              <span>{t.mode === "stream" ? "Streamed" : "Polled"}</span>
              <span>·</span>
              <span>
                {t.assistantIds.length} assistant {t.assistantIds.length === 1 ? "message" : "messages"}
              </span>
              <span className="ml-auto">
                <TurnStatus status={t.status} />
              </span>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-6 text-[11.5px] leading-relaxed text-faint">
        Timed in the browser from send to first sight of each assistant message. In polled mode, figures are accurate to
        about one second.
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="bg-surface px-4 py-4">
      <p className="text-[11.5px] text-muted">{label}</p>
      <p className="mt-1.5 font-display text-[26px] leading-none">{value}</p>
    </div>
  );
}

function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="text-[11px] text-faint">{label}</p>
      <p className="mt-0.5">{children}</p>
    </div>
  );
}

function TurnStatus({ status }: { status: Turn["status"] }) {
  if (status === "running")
    return (
      <span className="inline-flex items-center gap-1.5 text-accent">
        <Spinner className="size-3" /> Running
      </span>
    );
  if (status === "ok") return <span className="text-ok">Complete</span>;
  return <span className="font-medium text-danger capitalize">{status}</span>;
}

const SOURCE_ICON: Record<ToolSource, (p: { className?: string }) => ReactNode> = {
  calendar: Calendar,
  restaurants: Dining,
  memory: Memory,
};

function ActivityPanel({ activity, onClear }: { activity: Activity[]; onClear: () => void }) {
  if (!activity.length)
    return (
      <Empty title="Quiet so far">
        Tool calls, their source and duration, and any errors will appear here. Tool events arrive in streaming mode
        only.
      </Empty>
    );
  return (
    <div className="px-6 py-6">
      <div className="mb-3 flex items-center justify-between">
        <p className="eyebrow">Newest first</p>
        <button onClick={onClear} className="text-[12px] text-muted transition-colors hover:text-ink">
          Clear
        </button>
      </div>
      <ol className="flex flex-col">
        {[...activity].reverse().map((a) => (
          <li key={a.id} className="flex animate-fade gap-3.5 border-b border-line py-3.5 last:border-0">
            <ActivityIcon a={a} />
            <div className="min-w-0 flex-1">
              <ActivityBody a={a} />
            </div>
            <time className="shrink-0 pt-0.5 text-[11px] text-faint tabular-nums">{formatTime(a.at, true)}</time>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ActivityIcon({ a }: { a: Activity }) {
  const base = "flex size-8 shrink-0 items-center justify-center rounded-full text-[15px]";
  if (a.kind === "error")
    return (
      <span className={cx(base, "bg-danger-soft text-danger")}>
        <Alert />
      </span>
    );
  if (a.kind === "info")
    return (
      <span className={cx(base, "text-faint")}>
        <span className="size-1.5 rounded-full bg-line-strong" />
      </span>
    );
  const Icon = a.source ? SOURCE_ICON[a.source] : undefined;
  return (
    <span
      className={cx(
        base,
        a.status === "error"
          ? "bg-danger-soft text-danger"
          : a.status === "running"
            ? "bg-accent-soft text-accent"
            : "bg-sunken text-ink-soft",
      )}
    >
      {Icon ? <Icon /> : <Check />}
    </span>
  );
}

function ActivityBody({ a }: { a: Activity }) {
  if (a.kind === "info") return <p className="pt-1.5 text-[12.5px] text-muted">{a.text}</p>;
  if (a.kind === "error")
    return (
      <>
        <p className="pt-0.5 text-[13px] font-medium text-danger">{a.title}</p>
        <p className="mt-0.5 text-[12.5px] leading-relaxed break-words text-ink-soft">{a.detail}</p>
      </>
    );
  return (
    <>
      <div className="flex items-baseline justify-between gap-3 pt-0.5">
        <p className="truncate font-mono text-[12.5px] text-ink">{a.name}</p>
        <span className="shrink-0 text-[12px]">
          {a.status === "running" ? (
            <span className="inline-flex items-center gap-1.5 text-accent">
              <Spinner className="size-3" />
            </span>
          ) : (
            <Ms ms={a.durationMs} />
          )}
        </span>
      </div>
      <p className="mt-0.5 text-[12px] text-muted">
        <span className="capitalize">{a.source ?? "unknown source"}</span>
        {a.turnIndex !== undefined && <span className="text-faint"> · turn {a.turnIndex}</span>}
        {a.status === "error" && <span className="font-medium text-danger"> · error</span>}
      </p>
    </>
  );
}

function MemoriesPanel({ chat }: { chat: AgentChat }) {
  const { items, loading, error, fetchedAt, fresh } = chat.memories;
  const grouped = useMemo(() => {
    const m = new Map<string, typeof items>();
    for (const it of items) m.set(it.category, [...(m.get(it.category) ?? []), it]);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  return (
    <div className="px-6 py-6">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[12px] text-muted">
          {fetchedAt ? `Refreshed ${formatTime(fetchedAt, true)}` : "Not loaded"} · after every turn
        </p>
        <IconButton
          label="Refresh memories"
          className="size-8 text-[15px]"
          onClick={() => void chat.refreshMemories()}
          disabled={loading}
        >
          {loading ? <Spinner /> : <Refresh />}
        </IconButton>
      </div>

      {error && (
        <div className="mb-5 rounded-2xl border border-danger/15 bg-danger-soft px-4 py-3 text-[12.5px] text-danger">
          <p className="font-medium">
            {error.status > 0 && `${error.status} · `}
            {error.title}
          </p>
          <p className="mt-0.5 break-words text-danger/80">{error.detail}</p>
        </div>
      )}

      {!items.length && !loading && !error && (
        <Empty title="Nothing remembered">
          A new member starts with no memories. They'll appear here as the agent learns.
        </Empty>
      )}

      <div className="flex flex-col gap-7">
        {grouped.map(([cat, list]) => (
          <section key={cat}>
            <p className="mb-2.5 eyebrow">{cat.replace(/_/g, " ")}</p>
            <ul className="flex flex-col gap-2">
              {list.map((m) => (
                <li
                  key={m.id}
                  className={cx(
                    "rounded-2xl border bg-surface px-4 py-3.5 transition-colors duration-500",
                    fresh.has(m.id) ? "border-accent/40" : "border-line",
                  )}
                >
                  <p className="text-[13.5px] leading-relaxed text-ink">{m.content}</p>
                  <p className="mt-1.5 flex items-center gap-2 text-[11.5px] text-faint">
                    {fresh.has(m.id) && <span className="font-medium text-accent">Updated</span>}
                    <span title={m.updated_at}>{formatRelative(m.updated_at)}</span>
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
