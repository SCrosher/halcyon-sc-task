import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

const KEY = "halcyon:dev-mode";

/**
 * Ctrl/⌘ + Shift + . toggles developer mode. Five quick clicks on the header emblem also toggle it
 * (for embedded browsers that capture the shortcut, and touch devices). `?dev=1` / `?dev=0` sets it.
 */
function initial(): boolean {
  try {
    const param = new URLSearchParams(location.search).get("dev");
    if (param !== null) {
      const on = param === "1" || param === "true";
      localStorage.setItem(KEY, on ? "1" : "0");
      return on;
    }
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

const DevContext = createContext<{ dev: boolean; setDev: (v: boolean) => void; toggle: () => void }>({
  dev: false,
  setDev: () => {},
  toggle: () => {},
});

export function DevModeProvider({ children }: { children: ReactNode }) {
  const [dev, setDevState] = useState(initial);

  const setDev = useCallback((v: boolean) => {
    setDevState(v);
    try {
      localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(() => {
    setDevState((d) => {
      try {
        localStorage.setItem(KEY, d ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !d;
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Match by physical key or character, so it works across keyboard layouts.
      const period = e.code === "Period" || e.key === "." || e.key === ">";
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && !e.altKey && period && !e.repeat) {
        e.preventDefault();
        e.stopPropagation();
        toggle();
      }
    };
    // Capture phase, so nothing on the page can swallow it first.
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [toggle]);

  return <DevContext.Provider value={{ dev, setDev, toggle }}>{children}</DevContext.Provider>;
}

export function useDevMode() {
  return useContext(DevContext);
}
