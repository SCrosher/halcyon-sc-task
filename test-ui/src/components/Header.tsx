import { useRef } from "react";
import { useDevMode } from "../hooks/useDevMode";
import { APP_ENV } from "../lib/env";
import { shortId } from "../lib/format";
import type { Conversation } from "../lib/types";
import { Panels, Plus, Settings as SettingsIcon } from "./icons";
import { Emblem, Wordmark } from "./Logo";
import { cx, IconButton } from "./ui";

export function Header({
  conversationId,
  conversation,
  streaming,
  onStreamingChange,
  onNewConversation,
  onOpenSettings,
  onTogglePanel,
  busy,
}: {
  conversationId: string;
  conversation: Conversation | null;
  streaming: boolean;
  onStreamingChange: (v: boolean) => void;
  onNewConversation: () => void;
  onOpenSettings: () => void;
  onTogglePanel: () => void;
  busy: boolean;
}) {
  const { dev, setDev, toggle } = useDevMode();
  const status = conversation?.status ?? "new";
  const clicks = useRef<number[]>([]);

  const onEmblemClick = () => {
    const now = Date.now();
    clicks.current = [...clicks.current.filter((t) => now - t < 1500), now];
    if (clicks.current.length >= 5) {
      clicks.current = [];
      toggle();
    }
  };

  return (
    <header className="flex h-16 shrink-0 items-center gap-4 border-b border-line px-4 sm:px-6">
      <div className="flex items-center gap-3.5">
        {/* Also the touch-friendly dev-mode toggle (five quick clicks); keyboard users have the shortcut. */}
        <button type="button" onClick={onEmblemClick} tabIndex={-1} aria-label="Halcyon" className="select-none">
          <Emblem size={30} />
        </button>
        <Wordmark className="mt-px" />
      </div>

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        {dev && (
          <>
            <button
              onClick={() => setDev(false)}
              title="Leave developer mode"
              className="mr-1 inline-flex h-7 items-center gap-1.5 rounded-full border border-accent/25 bg-accent-soft px-3 text-[11.5px] font-medium text-accent transition-colors hover:border-accent/50"
            >
              Developer
              <span className="font-normal text-accent/70 capitalize">· {APP_ENV}</span>
            </button>

            <div className="mr-2 hidden items-center gap-2 text-[12px] text-muted md:flex" title={conversationId}>
              <span
                className={cx(
                  "size-1.5 rounded-full",
                  status === "processing" ? "bg-accent" : status === "idle" ? "bg-ok" : "bg-line-strong",
                )}
              />
              <span className="font-mono text-[11.5px]">{shortId(conversationId)}</span>
              <span className="text-faint capitalize">{status}</span>
            </div>

            <div
              className="mr-1 hidden h-8 items-center rounded-full bg-sunken p-0.5 text-[12px] sm:flex"
              title="Delivery mode"
            >
              {[
                { v: false, label: "Polling" },
                { v: true, label: "Streaming" },
              ].map((o) => (
                <button
                  key={o.label}
                  type="button"
                  aria-pressed={streaming === o.v}
                  disabled={busy}
                  onClick={() => onStreamingChange(o.v)}
                  className={cx(
                    "h-7 rounded-full px-3.5 transition-all duration-200",
                    streaming === o.v ? "bg-surface font-medium text-ink shadow-soft" : "text-muted hover:text-ink",
                  )}
                >
                  {o.label}
                </button>
              ))}
            </div>

            <IconButton label="Show panels" onClick={onTogglePanel} className="lg:hidden">
              <Panels />
            </IconButton>
            <IconButton label="Settings" onClick={onOpenSettings}>
              <SettingsIcon />
            </IconButton>
          </>
        )}

        <button
          onClick={onNewConversation}
          disabled={busy}
          className="inline-flex h-9 items-center gap-2 rounded-full px-3 text-[13px] text-ink-soft transition-colors duration-150 hover:bg-sunken hover:text-ink disabled:opacity-40 sm:px-4"
          title="New conversation"
        >
          <Plus className="text-[16px]" />
          <span className="hidden sm:inline">New conversation</span>
        </button>
      </div>
    </header>
  );
}
