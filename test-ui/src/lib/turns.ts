/** Client-side record of one turn, used for the latency metrics in developer mode. */

export type TurnStatus = "running" | "ok" | "error" | "interrupted";

export interface Turn {
  id: string;
  index: number;
  messageId: string;
  text: string;
  mode: "stream" | "poll";
  startedAt: Date;
  /** performance.now() at send. */
  t0: number;
  /** performance.now() each time a new assistant message was first seen. */
  arrivals: number[];
  assistantIds: string[];
  firstMs?: number;
  finalMs?: number;
  maxGapMs?: number;
  status: TurnStatus;
  errors: string[];
}

export function newTurn(id: string, index: number, messageId: string, text: string, mode: Turn["mode"]): Turn {
  return {
    id,
    index,
    messageId,
    text,
    mode,
    startedAt: new Date(),
    t0: performance.now(),
    arrivals: [],
    assistantIds: [],
    status: "running",
    errors: [],
  };
}

/** Longest wait for the member, counting from the send to the first message and between messages. */
export function longestGap(t0: number, arrivals: number[]): number | undefined {
  if (!arrivals.length) return undefined;
  let prev = t0;
  let max = 0;
  for (const a of arrivals) {
    max = Math.max(max, a - prev);
    prev = a;
  }
  return max;
}

/** The turn after an assistant message with this id was first seen at `at`. */
export function withArrival(turn: Turn, messageId: string, at: number): Turn {
  const arrivals = [...turn.arrivals, at];
  return {
    ...turn,
    arrivals,
    assistantIds: [...turn.assistantIds, messageId],
    firstMs: turn.firstMs ?? at - turn.t0,
    maxGapMs: longestGap(turn.t0, arrivals),
  };
}

export function finished(turn: Turn, status: TurnStatus, error?: string): Turn {
  return {
    ...turn,
    status,
    finalMs: turn.arrivals.length ? turn.arrivals[turn.arrivals.length - 1] - turn.t0 : undefined,
    errors: error ? [...turn.errors, error] : turn.errors,
  };
}

/** Resolves after `ms`, or rejects with an AbortError as soon as `signal` aborts. */
export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const t = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}
