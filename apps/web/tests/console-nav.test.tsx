import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { allowedSections } from "@/lib/console/sections";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst"],
  identities: [
    { user_id: "ana", display_name: "Ana Analyst", roles: ["analyst"] },
    { user_id: "rev", display_name: "Rae Reviewer", roles: ["pack_reviewer", "analyst"] },
    { user_id: "adm", display_name: "Ada Admin", roles: ["admin", "analyst"] },
  ],
  conversations: [],
};

function renderConsole(user: string, section: string | null) {
  window.localStorage.setItem("fitcher.demo.identity", user);
  const navigate = vi.fn();
  const onChat = vi.fn();
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={createMockApi()} navigate={vi.fn()} activeId={null} sources={{}}>
          <ConsoleLayout section={section} navigate={navigate} onChat={onChat}>
            <p>section page</p>
          </ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
  return { navigate, onChat };
}

const nav = () => screen.getByRole("navigation", { name: "Console" });
const links = () => within(nav()).getAllByRole("link").map((link) => link.textContent);

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("console sections", () => {
  it("gives each console role exactly its sections (DECISIONS §15)", () => {
    expect(allowedSections(["pack_reviewer"]).map((section) => section.key)).toEqual(["review", "documents", "datasets", "feedback", "evaluation"]);
    expect(allowedSections(["admin"]).map((section) => section.key)).toEqual(["runs", "audit", "costs", "evaluation", "users", "sources", "models"]);
    expect(allowedSections(["analyst", "marketing"])).toEqual([]);
  });

  it("hides the Users section in individual mode, which has no accounts", () => {
    expect(allowedSections(["admin"], "individual").map((section) => section.key)).not.toContain("users");
    expect(allowedSections(["admin"], "team").map((section) => section.key)).toContain("users");
  });

  it("lists a section once for a user with both console roles", () => {
    const keys = allowedSections(["admin", "pack_reviewer"]).map((section) => section.key);
    expect(keys.filter((key) => key === "evaluation")).toHaveLength(1);
    expect(keys).toHaveLength(11);
  });
});

describe("console layout", () => {
  it("shows a reviewer only the reviewer's sections, grouped, with the open one current", async () => {
    renderConsole("rev", "documents");

    await waitFor(() => expect(links()).toEqual(["Review", "Documents", "Datasets", "Feedback", "Evaluation", "Back to chat"]));
    expect(within(nav()).getByText("Knowledge")).toBeTruthy();
    expect(within(nav()).queryByText("Observe")).toBeNull();
    expect(within(nav()).getByRole("link", { name: "Documents" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("section page")).toBeTruthy();
  });

  it("sends a user without a console role to the chat app", async () => {
    const { onChat } = renderConsole("ana", "review");

    await waitFor(() => expect(onChat).toHaveBeenCalled());
    expect(screen.queryByText("section page")).toBeNull();
  });

  it("opens the first allowed section when none or a forbidden one is asked for", async () => {
    const { navigate } = renderConsole("adm", "review");

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/console/runs", { replace: true }));
    expect(screen.queryByText("section page")).toBeNull();
  });

  it("re-checks access when the identity changes on an open section", async () => {
    const { navigate } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Review"));

    fireEvent.click(screen.getByRole("button", { name: /Account menu: Rae Reviewer/ }));
    await act(async () => fireEvent.click(screen.getByRole("menuitem", { name: /Ada Admin/ })));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/console/runs", { replace: true }));
    expect(links()).toEqual(["Runs", "Audit", "Costs", "Evaluation", "Users", "Sources", "Models", "Back to chat"]);
  });

  it("opens the navigation as a drawer and closes it after a section is picked", async () => {
    const { navigate } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Datasets"));
    const app = document.querySelector(".fc-console");

    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    expect(app?.getAttribute("data-drawer")).toBe("open");
    fireEvent.click(within(nav()).getByRole("link", { name: "Datasets" }));

    expect(navigate).toHaveBeenCalledWith("/console/datasets");
    expect(app?.getAttribute("data-drawer")).toBeNull();
  });

  it("offers the chat app instead of the console from the account menu inside the console", async () => {
    const { onChat } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Review"));

    fireEvent.click(screen.getByRole("button", { name: /Account menu: Rae Reviewer/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Chat" }));

    expect(onChat).toHaveBeenCalled();
    expect(screen.queryByRole("menuitem", { name: "Workspace console" })).toBeNull();
  });
});
