import { describe, expect, it } from "vitest";
import { finished, longestGap, newTurn, sleep, withArrival } from "./turns";

describe("turn metrics", () => {
  it("measures the longest wait, including the wait for the first message", () => {
    expect(longestGap(0, [])).toBeUndefined();
    expect(longestGap(0, [3000, 4000, 12500])).toBe(8500);
    expect(longestGap(100, [9100])).toBe(9000);
  });

  it("records arrivals and the final time", () => {
    let turn = { ...newTurn("t1", 1, "m1", "hi", "stream"), t0: 1000 };
    turn = withArrival(turn, "a1", 3000);
    turn = withArrival(turn, "a2", 7000);
    expect(turn).toMatchObject({ firstMs: 2000, maxGapMs: 4000, assistantIds: ["a1", "a2"] });

    const done = finished(turn, "error", "Stream interrupted");
    expect(done).toMatchObject({ status: "error", finalMs: 6000, errors: ["Stream interrupted"] });
  });
});

describe("sleep", () => {
  it("rejects with an AbortError when aborted", async () => {
    const ctrl = new AbortController();
    const pending = sleep(10_000, ctrl.signal);
    ctrl.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
