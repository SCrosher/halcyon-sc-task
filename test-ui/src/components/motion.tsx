import { Fragment, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

const MAX_STAGGER_WORDS = 48;

/**
 * Wraps each word in a `.word` span with a stagger index. Words past MAX_STAGGER_WORDS share the
 * last index, so a long reply finishes animating in about 1.2 s.
 */
export function RevealText({ text }: { text: string }) {
  const parts = text.split(/(\s+)/);
  let w = 0;
  return (
    <>
      {parts.map((p, i) => {
        if (!p) return null;
        if (/^\s+$/.test(p)) return <Fragment key={i}>{p}</Fragment>;
        const idx = Math.min(w++, MAX_STAGGER_WORDS);
        return (
          <span key={i} className="word" style={{ "--i": idx } as CSSProperties}>
            {p}
          </span>
        );
      })}
    </>
  );
}

/**
 * Renders a growing string as one `.chunk` span per update, so only the newly added text animates.
 * Chunks are derived by diffing against the previous render; a non-prefix change starts over.
 */
export function StreamText({ text }: { text: string }) {
  const segments = useRef<string[]>([]);
  const length = useRef(0);

  if (text.length < length.current || !text.startsWith(segments.current.join(""))) {
    segments.current = [];
    length.current = 0;
  }
  if (text.length > length.current) {
    segments.current = [...segments.current, text.slice(length.current)];
    length.current = text.length;
  }

  return (
    <span className="caret">
      {segments.current.map((s, i) => (
        <span key={i} className="chunk">
          {s}
        </span>
      ))}
    </span>
  );
}

/**
 * Animates a change of `id`: the previous children stay mounted (`.swap-out`) until their exit
 * animation ends. Both occupy the same grid cell, so the swap doesn't shift the layout.
 */
export function Swap({ id, children, className }: { id: string; children: ReactNode; className?: string }) {
  const last = useRef({ id, node: children });
  const seq = useRef(0);
  const [leaving, setLeaving] = useState<{ key: number; node: ReactNode }[]>([]);

  // Remembers the latest children, and only queues an exit when the id changes.
  useLayoutEffect(() => {
    if (last.current.id !== id) {
      const old = last.current.node;
      const key = ++seq.current;
      setLeaving((ls) => [...ls, { key, node: old }]);
    }
    last.current = { id, node: children };
  }, [id, children]);

  return (
    <span className={`inline-grid ${className ?? ""}`}>
      {leaving.map((x) => (
        <span
          key={`out-${x.key}`}
          className="swap-out"
          style={{ gridArea: "1 / 1" }}
          aria-hidden
          onAnimationEnd={(e) => {
            if (e.target === e.currentTarget) setLeaving((ls) => ls.filter((y) => y.key !== x.key));
          }}
        >
          {x.node}
        </span>
      ))}
      <span key={`in-${id}`} className="swap-in" style={{ gridArea: "1 / 1" }}>
        {children}
      </span>
    </span>
  );
}

/** Keeps an element mounted for its exit animation after `show` turns false. */
export function usePresence(show: boolean, exitMs: number): { mounted: boolean; leaving: boolean } {
  const [mounted, setMounted] = useState(show);
  useEffect(() => {
    if (show) {
      setMounted(true);
      return;
    }
    const t = setTimeout(() => setMounted(false), exitMs);
    return () => clearTimeout(t);
  }, [show, exitMs]);
  return { mounted: show || mounted, leaving: !show && mounted };
}
