import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { keepQuestion, takeQuestion } from "@/lib/chat/pendingQuestion";

const chat = vi.hoisted(() => ({
  ask: vi.fn(async () => "c1"),
  pack: { name: "erp" } as { name: string } | null,
  loaded: true,
  providers: [{ id: "p" }] as { id: string }[],
}));

vi.mock("@/lib/chat/ChatContext", () => ({
  useChat: () => ({
    api: { chat: { suggestions: async () => [] }, models: { providers: async () => chat.providers } }, identity: null, pack: chat.pack, ask: chat.ask, busy: null, loaded: chat.loaded,
  }),
}));

import { EmptyChat } from "@/components/chat/EmptyChat";
import { I18nProvider } from "@/lib/i18n/react";

afterEach(() => {
  cleanup();
  chat.ask.mockClear();
  sessionStorage.clear();
});

describe("a question picked in the setup", () => {
  it("is kept for the tab and taken once", () => {
    keepQuestion("Orders per month?");
    expect(takeQuestion()).toBe("Orders per month?");
    expect(takeQuestion()).toBeNull();
  });

  it("is asked when the new chat opens with a pack", async () => {
    keepQuestion("Orders per month?");
    render(<I18nProvider initial="en"><EmptyChat /></I18nProvider>);

    await waitFor(() => expect(chat.ask).toHaveBeenCalledWith("Orders per month?"));
    expect(takeQuestion()).toBeNull();
  });

  it("is not asked, nor dropped, while there is no pack", async () => {
    chat.pack = null;
    keepQuestion("Orders per month?");
    render(<I18nProvider initial="en"><EmptyChat /></I18nProvider>);

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(chat.ask).not.toHaveBeenCalled();
    expect(takeQuestion()).toBe("Orders per month?");
    chat.pack = { name: "erp" };
  });
});

describe("a new chat without a pack", () => {
  it("points to connecting a model first when there is none", async () => {
    chat.pack = null;
    chat.providers = [];
    const { findByRole } = render(<I18nProvider initial="en"><EmptyChat /></I18nProvider>);

    expect(await findByRole("heading", { name: "Connect a model to start" })).toBeTruthy();
    expect((await findByRole("link", { name: "Open Models" })).getAttribute("href")).toBe("/console/models");
    chat.pack = { name: "erp" };
    chat.providers = [{ id: "p" }];
  });

  it("points to the data once a model is connected", async () => {
    chat.pack = null;
    const { findByRole } = render(<I18nProvider initial="en"><EmptyChat /></I18nProvider>);

    expect(await findByRole("heading", { name: "Connect your data to start" })).toBeTruthy();
    chat.pack = { name: "erp" };
  });
});
