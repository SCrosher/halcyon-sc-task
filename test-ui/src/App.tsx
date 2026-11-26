import { useCallback, useEffect, useState } from "react";
import { Chat } from "./components/Chat";
import { Header } from "./components/Header";
import { Close } from "./components/icons";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { SidePanel } from "./components/SidePanel";
import { IconButton } from "./components/ui";
import { useAgentChat } from "./hooks/useAgentChat";
import { useDevMode } from "./hooks/useDevMode";
import { loadSettings, resolveToken, saveSettings, type Settings } from "./lib/settings";
import { uuid } from "./lib/uuid";

export default function App() {
  const { dev } = useDevMode();
  const [settings, setSettingsState] = useState<Settings>(loadSettings);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);

  const setSettings = useCallback((s: Settings) => {
    setSettingsState(s);
    saveSettings(s);
  }, []);

  useEffect(() => {
    if (!dev) {
      setSettingsOpen(false);
      setPanelOpen(false);
    }
  }, [dev]);

  useEffect(() => {
    if (!panelOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPanelOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panelOpen]);

  const chat = useAgentChat(settings);
  const connected = resolveToken(settings).length > 0;

  return (
    <div className="flex h-full flex-col">
      <Header
        conversationId={settings.conversationId}
        conversation={chat.conversation}
        streaming={settings.streaming}
        busy={chat.busy}
        onStreamingChange={(streaming) => setSettings({ ...settings, streaming })}
        onNewConversation={() => setSettings({ ...settings, conversationId: uuid() })}
        onOpenSettings={() => setSettingsOpen(true)}
        onTogglePanel={() => setPanelOpen((o) => !o)}
      />

      <div className="flex min-h-0 flex-1">
        <Chat chat={chat} memberName={settings.memberName} memberId={settings.memberId} connected={connected} />

        {dev && (
          <aside className="hidden w-[400px] shrink-0 animate-slide-in border-l border-line bg-surface/50 lg:block xl:w-[440px]">
            <SidePanel chat={chat} />
          </aside>
        )}
      </div>

      {dev && panelOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          {/* Backdrop: a mouse/touch shortcut for the close button and Escape. */}
          <div
            aria-hidden
            role="presentation"
            className="absolute inset-0 animate-fade bg-ink/20"
            onClick={() => setPanelOpen(false)}
          />
          <div className="absolute inset-y-0 right-0 flex w-full max-w-[440px] animate-slide-in flex-col bg-canvas shadow-lift">
            <div className="absolute top-3 right-3 z-10">
              <IconButton label="Close panels" onClick={() => setPanelOpen(false)}>
                <Close />
              </IconButton>
            </div>
            <SidePanel chat={chat} />
          </div>
        </div>
      )}

      <SettingsDrawer
        open={dev && settingsOpen}
        settings={settings}
        onClose={() => setSettingsOpen(false)}
        onSave={(s) => {
          setSettings(s);
          setSettingsOpen(false);
        }}
      />
    </div>
  );
}
