import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { AgentChat } from "../hooks/useAgentChat";
import { Chat } from "./Chat";

beforeAll(() => {
  Element.prototype.scrollTo = () => {}; // not implemented by jsdom
});
afterEach(cleanup);

function fakeChat(overrides: Partial<AgentChat> = {}): AgentChat {
  return {
    items: [],
    draft: null,
    activeTool: null,
    turns: [],
    activity: [],
    conversation: null,
    historyError: null,
    historyLoading: false,
    busy: false,
    memories: { items: [], loading: false, fresh: new Set() },
    send: vi.fn<AgentChat["send"]>(),
    retry: vi.fn<AgentChat["retry"]>(),
    resendDuplicate: vi.fn<AgentChat["resendDuplicate"]>(async () => {}),
    refreshMemories: vi.fn<AgentChat["refreshMemories"]>(async () => {}),
    clearActivity: vi.fn<AgentChat["clearActivity"]>(),
    ...overrides,
  };
}

describe("Chat", () => {
  it("greets the member by first name and sends a suggestion", () => {
    const chat = fakeChat();
    render(<Chat chat={chat} memberName="Jane Doe" memberId="u1" connected />);
    expect(screen.getByRole("heading").textContent).toMatch(/, Jane\.$/);

    fireEvent.click(screen.getByText("What is in my diary tomorrow?"));
    expect(chat.send).toHaveBeenCalledWith("What is in my diary tomorrow?");
  });

  it("sends on Enter and keeps Shift+Enter for new lines", () => {
    const chat = fakeChat();
    render(<Chat chat={chat} memberName="Jane Doe" memberId="u1" connected />);
    const box = screen.getByLabelText("Message");

    fireEvent.change(box, { target: { value: "Dinner for two on Friday" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(chat.send).not.toHaveBeenCalled();

    fireEvent.keyDown(box, { key: "Enter" });
    expect(chat.send).toHaveBeenCalledWith("Dinner for two on Friday");
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("can't send without a connection", () => {
    const chat = fakeChat();
    render(<Chat chat={chat} memberName="Jane Doe" memberId="u1" connected={false} />);
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "hello" } });
    expect((screen.getByLabelText("Send") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Not connected")).toBeTruthy();
  });

  it("shows the conversation's messages", () => {
    const items = [
      { id: "m1", role: "member" as const, text: "Somewhere nice on Thursday?", created_at: "2026-11-26T18:00:00Z" },
      { id: "a1", role: "assistant" as const, text: "Verdant has 19:30 free.", created_at: "2026-11-26T18:00:05Z" },
    ];
    render(<Chat chat={fakeChat({ items })} memberName="Jane Doe" memberId="u1" connected />);
    expect(screen.getByText("Somewhere nice on Thursday?")).toBeTruthy();
    expect(screen.getByText("Verdant has 19:30 free.")).toBeTruthy();
    expect(screen.queryByRole("heading")).toBeNull();
  });
});
