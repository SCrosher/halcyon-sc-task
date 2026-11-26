import { useCallback, useState } from "react";
import { asApiError } from "../lib/api";
import type { ToolSource } from "../lib/types";
import { uuid } from "../lib/uuid";

/** One row of the developer Activity panel. */
export type Activity =
  | {
      id: string;
      kind: "tool";
      at: Date;
      turnIndex?: number;
      toolUseId: string;
      name: string;
      source?: ToolSource;
      status: "running" | "ok" | "error";
      durationMs?: number;
    }
  | { id: string; kind: "error"; at: Date; turnIndex?: number; title: string; detail: string }
  | { id: string; kind: "info"; at: Date; turnIndex?: number; text: string };

/** An Activity without the fields the log fills in (distributes Omit over the union). */
type NewActivity = Activity extends infer A ? (A extends Activity ? Omit<A, "id" | "at"> : never) : never;

export interface ToolFinished {
  toolUseId: string;
  name: string;
  isError: boolean;
  durationMs: number;
  turnIndex: number;
}

export function useActivityLog() {
  const [activity, setActivity] = useState<Activity[]>([]);

  const log = useCallback((entry: NewActivity) => {
    setActivity((a) => [...a, { id: uuid(), at: new Date(), ...entry } as Activity]);
  }, []);

  const logError = useCallback(
    (e: unknown, turnIndex?: number) => {
      const err = asApiError(e);
      const title = err.status > 0 ? `${err.status} · ${err.title}` : err.title;
      log({ kind: "error", title, detail: err.detail, turnIndex });
    },
    [log],
  );

  /** Completes the tool's "running" row, or adds a finished one if its start was never seen. */
  const finishTool = useCallback((t: ToolFinished) => {
    setActivity((xs) => {
      const done = { status: t.isError ? "error" : "ok", durationMs: t.durationMs } as const;
      const i = xs.findIndex((x) => x.kind === "tool" && x.toolUseId === t.toolUseId);
      if (i < 0) {
        const row: Activity = {
          id: uuid(),
          kind: "tool",
          at: new Date(),
          turnIndex: t.turnIndex,
          toolUseId: t.toolUseId,
          name: t.name,
          ...done,
        };
        return [...xs, row];
      }
      const copy = xs.slice();
      copy[i] = { ...(copy[i] as Extract<Activity, { kind: "tool" }>), ...done };
      return copy;
    });
  }, []);

  const clear = useCallback(() => setActivity([]), []);

  return { activity, log, logError, finishTool, clear };
}
