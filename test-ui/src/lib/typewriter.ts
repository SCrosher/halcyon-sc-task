/**
 * Paces streamed text onto the screen at a steady, readable rate.
 *
 * The model's deltas arrive in quick bursts (a short reply can land in well under a second), so
 * showing them as they come looks like the whole message popping in. Text is buffered and revealed
 * at BASE_CHARS_PER_SEC, faster while a backlog builds up (see MAX_LAG_MS).
 * Progress is driven by elapsed time, so throttled timers in a background tab just catch up.
 */

const BASE_CHARS_PER_SEC = 75;
/**
 * Each tick runs at the rate that would clear the current backlog in this time. As the backlog shrinks
 * the rate eases off, so a burst drains smoothly (~63% of it per MAX_LAG_MS) instead of all at once.
 */
const MAX_LAG_MS = 700;
const TICK_MS = 16;

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export class Typewriter {
  private target = "";
  /** Characters revealed so far; fractional between ticks. */
  private shown = 0;
  private last = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private waiters: (() => void)[] = [];
  private readonly onChange: (text: string) => void;

  constructor(onChange: (text: string) => void) {
    this.onChange = onChange;
  }

  push(text: string): void {
    if (!text) return;
    this.target += text;
    if (prefersReducedMotion() || (typeof document !== "undefined" && document.hidden)) {
      this.flush();
      return;
    }
    if (this.timer === null) {
      this.last = performance.now();
      this.schedule();
    }
  }

  /** Resolves once everything pushed so far is on screen (immediately if the signal aborts). */
  drain(signal?: AbortSignal): Promise<void> {
    if (this.shown >= this.target.length || signal?.aborted) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        signal?.removeEventListener("abort", done);
        resolve();
      };
      signal?.addEventListener("abort", done, { once: true });
      this.waiters.push(done);
    });
  }

  /** Clears the text for the next message. */
  reset(): void {
    this.stop();
    this.target = "";
    this.shown = 0;
  }

  /** Stops ticking and releases anyone waiting in drain(). */
  stop(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.release();
  }

  private flush(): void {
    this.shown = this.target.length;
    this.onChange(this.target);
    this.stop();
  }

  private schedule(): void {
    this.timer = setTimeout(() => this.tick(), TICK_MS);
  }

  private tick(): void {
    const now = performance.now();
    const dt = (now - this.last) / 1000;
    this.last = now;
    const backlog = this.target.length - this.shown;
    const rate = Math.max(BASE_CHARS_PER_SEC, backlog / (MAX_LAG_MS / 1000));
    // Fractional progress carries over, so the rate holds however the ticks fall.
    this.shown = Math.min(this.target.length, this.shown + rate * dt);
    let end = Math.floor(this.shown);
    // Don't split an emoji (surrogate pair) across ticks.
    if (end < this.target.length && /[\uD800-\uDBFF]/.test(this.target[end - 1] ?? "")) end += 1;
    this.onChange(this.target.slice(0, end));
    if (this.shown >= this.target.length) {
      this.timer = null;
      this.release();
    } else {
      this.schedule();
    }
  }

  private release(): void {
    const waiters = this.waiters;
    this.waiters = [];
    for (const w of waiters) w();
  }
}
