import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Typewriter } from "./typewriter";

beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] }));
afterEach(() => vi.useRealTimers());

describe("Typewriter", () => {
  it("reveals text gradually and resolves drain() once it is all shown", async () => {
    const shown: string[] = [];
    const tw = new Typewriter((t) => shown.push(t));
    tw.push("Hello there, how can I help?");

    let drained = false;
    void tw.drain().then(() => (drained = true));
    await vi.advanceTimersByTimeAsync(50);
    expect(shown.at(-1)!.length).toBeLessThan(28);
    expect(drained).toBe(false);

    await vi.advanceTimersByTimeAsync(1000);
    expect(shown.at(-1)).toBe("Hello there, how can I help?");
    expect(drained).toBe(true);
  });

  it("speeds up to work through a large backlog", async () => {
    const shown: string[] = [];
    const tw = new Typewriter((t) => shown.push(t));
    tw.push("x".repeat(2000));
    await vi.advanceTimersByTimeAsync(700);
    // Far beyond the base rate (~53 chars in 700 ms): most of the burst is already on screen.
    expect(shown.at(-1)!.length).toBeGreaterThan(1000);
    await vi.advanceTimersByTimeAsync(4000);
    expect(shown.at(-1)).toHaveLength(2000);
  });

  it("releases waiters when stopped and starts over after reset", async () => {
    const shown: string[] = [];
    const tw = new Typewriter((t) => shown.push(t));
    tw.push("first message");
    const drained = tw.drain();
    tw.reset();
    await drained;

    tw.push("second");
    await vi.advanceTimersByTimeAsync(1000);
    expect(shown.at(-1)).toBe("second");
  });
});
