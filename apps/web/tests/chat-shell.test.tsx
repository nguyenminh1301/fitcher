import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatLayout } from "@/components/chat/ChatLayout";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile, ConversationThread } from "@/lib/api/provisional";
import type { Sources } from "@/lib/api/sources";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

const NOW = new Date("2026-11-03T12:00:00Z");

function thread(id: string, title: string, updated: string, extra: Partial<ConversationThread["conversation"]> = {}): ConversationThread {
  return { conversation: { id, title, pinned: false, group_id: null, updated_at: updated, ...extra }, turns: [{ turn: 1, revision: 1, question: title, question_lang: "en", events: [] }] };
}

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst", "marketing"],
  identities: [
    { user_id: "ana", display_name: "Ana Analyst", roles: ["analyst"] },
    { user_id: "rev", display_name: "Rae Reviewer", roles: ["pack_reviewer", "analyst"] },
  ],
  conversations: [
    thread("today", "Sales today", "2026-11-03T09:00:00Z"),
    thread("week", "Sales this week", "2026-10-30T09:00:00Z"),
    thread("month", "Sales last month", "2026-10-10T09:00:00Z"),
    thread("pinned", "Pinned report", "2026-10-01T09:00:00Z", { pinned: true }),
  ],
};

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
}

function renderShell(options: { sources?: Partial<Sources>; locale?: "en" | "vi" } = {}) {
  const navigate = vi.fn();
  const api = createMockApi();
  render(
    <ThemeProvider>
    <I18nProvider initial={options.locale ?? "en"}>
      <ChatProvider api={api} navigate={navigate} activeId={null} sources={options.sources} now={() => NOW}>
        <ChatLayout>
          <p>page</p>
        </ChatLayout>
      </ChatProvider>
    </I18nProvider>
    </ThemeProvider>,
  );
  return { navigate, api };
}

beforeEach(() => {
  window.localStorage.clear();
  stubFetch();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const sidebar = () => screen.getByRole("navigation", { name: "History" });

describe("chat sidebar", () => {
  it("orders pinned, then recent conversations by today, past week and past month", async () => {
    renderShell();
    await screen.findByText("Sales today");

    const text = sidebar().textContent ?? "";
    const order = ["Pinned", "Pinned report", "Recent", "Today", "Sales today", "Past week", "Sales this week", "Past month", "Sales last month"].map((part) => text.indexOf(part));
    expect(order.every((position) => position >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("deletes a conversation only after confirming", async () => {
    renderShell();
    await screen.findByText("Sales today");

    fireEvent.click(screen.getByRole("button", { name: /Options for Sales today|Sales today/i, expanded: false }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByText("Sales today")).toBeNull());
  });

  it("opens search with Ctrl K and opens a result with the arrow keys and Enter", async () => {
    const { navigate } = renderShell();
    await screen.findByText("Sales today");

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "sales" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(navigate).toHaveBeenCalledWith("week");
  });

  it("resizes between 220 and 440 pixels with the arrow keys and resets on double-click", async () => {
    renderShell();
    await screen.findByText("Sales today");
    const handle = screen.getByRole("separator", { name: /Resize/ });

    for (let i = 0; i < 30; i += 1) fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle.getAttribute("aria-valuenow")).toBe("440");
    for (let i = 0; i < 30; i += 1) fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle.getAttribute("aria-valuenow")).toBe("220");
    fireEvent.doubleClick(handle);
    expect(handle.getAttribute("aria-valuenow")).toBe("272");
  });
});

describe("account menu", () => {
  async function openAccount() {
    fireEvent.click(await screen.findByRole("button", { name: /Account menu/ }));
    return screen.findByRole("menu");
  }

  it("offers the demo identities while sign-in is on sample data, and switching reloads the history", async () => {
    const { api } = renderShell();
    await screen.findByText("Sales today");
    await api.conversations.save(thread("ana-only", "Only for Ana", "2026-11-03T10:00:00Z"));

    const menu = await openAccount();
    await act(async () => fireEvent.click(within(menu).getByRole("menuitem", { name: /Rae Reviewer/ })));

    await waitFor(() => expect(screen.queryByText("Only for Ana")).toBeNull());
    expect(screen.getByText("Sales today")).toBeTruthy();
  });

  it("hides the identity picker once sign-in is wired", async () => {
    renderShell({ sources: { auth: "http" } });
    await screen.findByText("Sales today");

    const menu = await openAccount();

    expect(within(menu).queryByRole("menuitem", { name: /Rae Reviewer/ })).toBeNull();
  });

  it("shows the console entry only to console roles", async () => {
    renderShell();
    await screen.findByText("Sales today");
    let menu = await openAccount();
    expect(within(menu).queryByRole("menuitem", { name: "Workspace console" })).toBeNull();

    await act(async () => fireEvent.click(within(menu).getByRole("menuitem", { name: /Rae Reviewer/ })));
    menu = await openAccount();

    expect(within(menu).getByRole("menuitem", { name: "Workspace console" })).toBeTruthy();
  });
});

describe("interface language", () => {
  it("translates labels but never conversation titles", async () => {
    renderShell({ locale: "vi" });
    await screen.findByText("Sales today");

    expect(screen.getByRole("navigation", { name: "Lịch sử" })).toBeTruthy();
    expect(screen.getByText("Sales today")).toBeTruthy();
  });
});
