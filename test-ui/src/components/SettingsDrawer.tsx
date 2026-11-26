import { useEffect, useState, type ReactNode } from "react";
import { DEFAULT_API_URL, DEMO_MEMBER, defaultSettings, randomMember, type Settings } from "../lib/settings";
import { APP_ENV, DEFAULT_AGENT_TOKEN, DEPLOYED_API_URL, LOCAL_API_URL } from "../lib/env";
import { uuid } from "../lib/uuid";
import { Close, Eye, EyeOff, Plus, Shuffle } from "./icons";
import { Button, CopyButton, cx, Field, IconButton, inputClass, Toggle } from "./ui";

export function SettingsDrawer({
  open,
  settings,
  onClose,
  onSave,
}: {
  open: boolean;
  settings: Settings;
  onClose: () => void;
  onSave: (s: Settings) => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    if (open) setDraft(settings);
  }, [open, settings]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const isDemo = draft.memberId === DEMO_MEMBER.id;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop: a mouse/touch shortcut for the close button and Escape. */}
      <div
        aria-hidden
        role="presentation"
        className="absolute inset-0 animate-fade bg-ink/20 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <aside
        // A styled drawer rather than <dialog>, whose default positioning and backdrop fight the layout.
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        className="absolute inset-y-0 right-0 flex w-full max-w-[460px] animate-slide-in flex-col bg-canvas shadow-lift"
      >
        <header className="flex h-16 items-center justify-between border-b border-line px-6 sm:px-8">
          <h2 className="font-display text-[24px] font-medium">Settings</h2>
          <IconButton label="Close settings" onClick={onClose}>
            <Close />
          </IconButton>
        </header>

        <form
          className="flex-1 scrollbar-quiet overflow-y-auto px-6 py-8 sm:px-8"
          onSubmit={(e) => {
            e.preventDefault();
            onSave({ ...draft, apiBaseUrl: draft.apiBaseUrl.trim(), token: draft.token.trim() });
          }}
          id="settings-form"
        >
          <Section title="Connection">
            <Field
              label="API base URL"
              hint={
                <>
                  Leave blank to use this build’s {APP_ENV === "local" ? "local" : APP_ENV} API.
                  {DEPLOYED_API_URL && (
                    <>
                      {" "}
                      <button
                        type="button"
                        className="underline decoration-line-strong underline-offset-4 hover:text-ink"
                        onClick={() => set("apiBaseUrl", draft.apiBaseUrl ? "" : LOCAL_API_URL)}
                      >
                        {draft.apiBaseUrl ? `Use ${APP_ENV}` : "Use localhost"}
                      </button>
                    </>
                  )}
                </>
              }
            >
              <input
                className={inputClass}
                value={draft.apiBaseUrl}
                placeholder={DEFAULT_API_URL}
                onChange={(e) => set("apiBaseUrl", e.target.value)}
                spellCheck={false}
                autoComplete="off"
                inputMode="url"
              />
            </Field>
            <Field
              label="Bearer token"
              hint={
                DEFAULT_AGENT_TOKEN && !draft.token
                  ? "Using this environment's default token. Paste one to override it."
                  : "Stored in this browser only. Sent as Authorization: Bearer on every call."
              }
            >
              <div className="relative">
                <input
                  className={cx(inputClass, "pr-12 font-mono text-[13px]")}
                  type={showToken ? "text" : "password"}
                  value={draft.token}
                  onChange={(e) => set("token", e.target.value)}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="Paste token"
                />
                <IconButton
                  type="button"
                  label={showToken ? "Hide token" : "Show token"}
                  className="absolute top-1 right-1"
                  onClick={() => setShowToken((s) => !s)}
                >
                  {showToken ? <EyeOff /> : <Eye />}
                </IconButton>
              </div>
            </Field>
          </Section>

          <Section
            title="Member"
            aside={
              <Button
                type="button"
                variant="ghost"
                className="-mr-3 h-8 px-3 text-[12.5px]"
                onClick={() => {
                  const m = randomMember();
                  setDraft((d) => ({ ...d, memberId: m.id, memberName: m.name, conversationId: uuid() }));
                }}
              >
                <Shuffle /> New random member
              </Button>
            }
          >
            <Field
              label="Member ID"
              hint={
                isDemo
                  ? "Demo member."
                  : "A new member tests a cold start with no memories. Switching also starts a new conversation."
              }
            >
              <IdInput value={draft.memberId} onChange={(v) => set("memberId", v)} />
            </Field>
            <Field label="Name">
              <input
                className={inputClass}
                value={draft.memberName}
                onChange={(e) => set("memberName", e.target.value)}
              />
            </Field>
            {!isDemo && (
              <button
                type="button"
                className="text-[12.5px] text-muted underline decoration-line-strong underline-offset-4 hover:text-ink"
                onClick={() =>
                  setDraft((d) => ({
                    ...d,
                    memberId: DEMO_MEMBER.id,
                    memberName: DEMO_MEMBER.name,
                    conversationId: uuid(),
                  }))
                }
              >
                Back to {DEMO_MEMBER.name}
              </button>
            )}
          </Section>

          <Section
            title="Conversation"
            aside={
              <Button
                type="button"
                variant="ghost"
                className="-mr-3 h-8 px-3 text-[12.5px]"
                onClick={() => set("conversationId", uuid())}
              >
                <Plus /> New conversation
              </Button>
            }
          >
            <Field label="Conversation ID">
              <IdInput value={draft.conversationId} onChange={(v) => set("conversationId", v)} />
            </Field>
          </Section>

          <Section title="Delivery">
            <Toggle
              checked={draft.streaming}
              onChange={(v) => set("streaming", v)}
              label="Stream responses"
              description="Server-sent events with live drafts and tool activity. When off, the console polls every second after the 202."
            />
          </Section>

          <button
            type="button"
            className="mt-2 text-[12.5px] text-muted underline decoration-line-strong underline-offset-4 hover:text-ink"
            onClick={() => setDraft({ ...defaultSettings(), token: draft.token })}
          >
            Restore defaults (keeps token)
          </button>
        </form>

        <footer className="flex items-center justify-end gap-2 border-t border-line px-6 py-4 sm:px-8">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="settings-form" variant="primary" disabled={!dirty} className="px-6">
            Save changes
          </Button>
        </footer>
      </aside>
    </div>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-10">
      <div className="mb-5 flex h-8 items-center justify-between">
        <h3 className="eyebrow">{title}</h3>
        {aside}
      </div>
      <div className="flex flex-col gap-5">{children}</div>
    </section>
  );
}

function IdInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative">
      <input
        className={cx(inputClass, "pr-11 font-mono text-[12.5px]")}
        value={value}
        onChange={(e) => onChange(e.target.value.trim())}
        spellCheck={false}
        autoComplete="off"
      />
      <span className="absolute top-2 right-2">
        <CopyButton value={value} />
      </span>
    </div>
  );
}
