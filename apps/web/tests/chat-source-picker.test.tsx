import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EmptyChat } from "@/components/chat/EmptyChat";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import type { AskRequest, SourceView } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst"],
  identities: [{ user_id: "ana", display_name: "Ana Analyst", roles: ["analyst", "admin"] }],
  conversations: [],
};

function source(id: string, status: "ready" | "none"): SourceView {
  return { id, kind: "file", host: null, port: null, database: null, schema_name: null, user: null, tls_mode: "prefer", has_ca: false,
           created_at: "2026-11-01T08:00:00Z", table_count: 1, selected_count: 1, last_sync: null,
           pack: { name: id, status, datasets: 1, error: null } };
}

function show() {
  const api = createMockApi();
  const asked: AskRequest[] = [];
  Object.assign(api.sources, { list: vi.fn(async () => [source("shop", "ready"), source("crm", "ready"), source("raw", "none")]) });
  Object.assign(api.chat, {
    ask: vi.fn(async function* (request: AskRequest) { asked.push(request); }),
    suggestions: vi.fn(async () => []),
  });
  Object.assign(api.auth, { choosePack: vi.fn(async (name: string) => ({ name, display_name: name, roles: ["analyst"] })) });
  render(
    <I18nProvider initial="en">
      <ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{}}><EmptyChat /></ChatProvider>
    </I18nProvider>,
  );
  return { asked, api };
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the data source of a new conversation", () => {
  it("offers the sources that can answer in a menu, makes the chosen one current and sends it with the first question", async () => {
    const { asked, api } = show();
    fireEvent.click(await screen.findByRole("button", { name: "Source: shop. Choose another" }));
    const menu = await screen.findByRole("menu");

    const items = within(menu).getAllByRole("menuitem").map((item) => item.textContent);
    expect(items).toEqual(["shop1 dataset", "crm1 dataset", "Manage sources"]);
    await act(async () => fireEvent.click(within(menu).getByRole("menuitem", { name: /crm/ })));
    expect(api.auth.choosePack).toHaveBeenCalledWith("crm");
    expect(await screen.findByRole("button", { name: "Source: crm. Choose another" })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "How many leads?" } });
    await act(async () => fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" }));

    await waitFor(() => expect(asked).toHaveLength(1));
    expect(asked[0].pack).toBe("crm");
  });

  it("starts from the source chosen on the Sources page", async () => {
    window.sessionStorage.setItem("fitcher.chosenPack", "crm");
    show();

    expect(await screen.findByRole("button", { name: "Source: crm. Choose another" })).toBeTruthy();
  });
});
