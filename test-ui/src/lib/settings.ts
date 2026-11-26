import { DEFAULT_AGENT_TOKEN, DEPLOYED_API_URL, LOCAL_API_URL } from "./env";
import { uuid } from "./uuid";

export interface Settings {
  /** Override for the agent API. Empty means this build's default (see DEFAULT_API_URL). */
  apiBaseUrl: string;
  token: string;
  memberId: string;
  memberName: string;
  conversationId: string;
  streaming: boolean;
}

export const DEMO_MEMBER = { id: "7c1e4b2a-5f3d-4e8c-a9b6-2d1f0e7c3b45", name: "Jane Doe" } as const;

export const DEFAULT_API_URL = DEPLOYED_API_URL ?? LOCAL_API_URL;

export function resolveApiUrl(s: Settings): string {
  return s.apiBaseUrl.trim() || DEFAULT_API_URL;
}

/** The saved token, or this environment's default token when none is saved. */
export function resolveToken(s: Settings): string {
  return s.token.trim() || DEFAULT_AGENT_TOKEN;
}

const KEY = "halcyon:settings:v2";

export function defaultSettings(): Settings {
  return {
    apiBaseUrl: "",
    token: "",
    memberId: DEMO_MEMBER.id,
    memberName: DEMO_MEMBER.name,
    conversationId: uuid(),
    streaming: false,
  };
}

export function loadSettings(): Settings {
  const defaults = defaultSettings();
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    const merged: Settings = { ...defaults };
    for (const k of Object.keys(defaults) as (keyof Settings)[]) {
      if (typeof parsed[k] === typeof defaults[k]) (merged as unknown as Record<string, unknown>)[k] = parsed[k];
    }
    return merged;
  } catch {
    return defaults;
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable (private mode, blocked) — settings live for this session only */
  }
}

const FIRST = ["Alexandra", "Theo", "Margaux", "Julian", "Isabella", "Sebastian", "Celeste", "Hugo", "Olivia", "Felix"];
const LAST = ["Ashford", "Laurent", "Whitmore", "Castellane", "Sinclair", "Hartley", "Moreau", "Kensington"];

function pick<T>(xs: readonly T[]): T {
  return xs[Math.floor(Math.random() * xs.length)];
}

export function randomMember(): { id: string; name: string } {
  return { id: uuid(), name: `${pick(FIRST)} ${pick(LAST)}` };
}
