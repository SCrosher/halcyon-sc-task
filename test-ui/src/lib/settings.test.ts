import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_API_URL, DEMO_MEMBER, loadSettings, resolveApiUrl, saveSettings } from "./settings";

const KEY = "halcyon:settings:v2";

beforeEach(() => localStorage.clear());

describe("settings", () => {
  it("defaults to the demo member and a new conversation", () => {
    const s = loadSettings();
    expect(s.memberId).toBe(DEMO_MEMBER.id);
    expect(s.conversationId).toMatch(/^[0-9a-f-]{36}$/);
    expect(s.streaming).toBe(false);
  });

  it("round-trips through localStorage", () => {
    const s = { ...loadSettings(), token: "abc", streaming: true };
    saveSettings(s);
    expect(loadSettings()).toEqual(s);
  });

  it("ignores stored values of the wrong type and unreadable JSON", () => {
    localStorage.setItem(KEY, JSON.stringify({ streaming: "yes", memberName: "Theo" }));
    const s = loadSettings();
    expect(s.streaming).toBe(false);
    expect(s.memberName).toBe("Theo");

    localStorage.setItem(KEY, "{not json");
    expect(loadSettings().memberId).toBe(DEMO_MEMBER.id);
  });

  it("falls back to the build's API URL when none is set", () => {
    const s = loadSettings();
    expect(resolveApiUrl({ ...s, apiBaseUrl: "  " })).toBe(DEFAULT_API_URL);
    expect(resolveApiUrl({ ...s, apiBaseUrl: " http://x.test " })).toBe("http://x.test");
  });
});
