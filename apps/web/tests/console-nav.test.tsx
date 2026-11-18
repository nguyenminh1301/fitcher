import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { sectionOf, SECTIONS } from "@/lib/console/sections";
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

function renderConsole(user: string, section: string) {
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
  it("lists every page for the owner, with the Overview first", () => {
    expect(SECTIONS.map((section) => section.key)).toEqual([
      "overview", "sources", "datasets", "documents", "review", "feedback", "evaluation", "runs", "costs", "audit", "models", "security",
    ]);
    expect(sectionOf("/console")).toBe("overview");
    expect(sectionOf("/console/runs/abc")).toBe("runs");
  });
});

describe("console layout", () => {
  it("shows every page grouped as Data, Quality, Activity and Settings, with the open one current", async () => {
    renderConsole("rev", "documents");

    await waitFor(() => expect(links()).toEqual([
      "Shop", "Overview", "Sources", "Datasets", "Documents", "Review", "Feedback", "Evaluation", "Runs", "Costs", "Query log", "Models", "Security", "Chat",
    ]));
    for (const group of ["Data", "Quality", "Activity", "Settings"]) expect(within(nav()).getByText(group)).toBeTruthy();
    expect(within(nav()).getByRole("link", { name: "Documents" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("section page")).toBeTruthy();
  });

  it("names the active pack at the top, and opening it shows the datasets", async () => {
    const { navigate } = renderConsole("rev", "overview");
    const packLink = await within(nav()).findByRole("link", { name: /Shop/ });

    fireEvent.click(packLink);
    expect(navigate).toHaveBeenCalledWith("/console/datasets");
  });

  it("opens the navigation as a drawer and closes it after a page is picked", async () => {
    const { navigate } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Datasets"));
    const app = document.querySelector(".cs");

    fireEvent.click(screen.getByRole("button", { name: "Open the menu" }));
    expect(app?.getAttribute("data-drawer")).toBe("open");
    fireEvent.click(within(nav()).getByRole("link", { name: "Datasets" }));

    expect(navigate).toHaveBeenCalledWith("/console/datasets");
    expect(app?.getAttribute("data-drawer")).toBe("closed");
  });

  it("offers the chat and the Security page from the owner menu, and no sign-out without a password", async () => {
    const { onChat, navigate } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Review"));

    fireEvent.click(await within(nav()).findByRole("button", { name: "Owner menu" }));
    expect(screen.getByRole("radiogroup", { name: "Theme" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Sign out" })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Security and owner password" }));
    expect(navigate).toHaveBeenCalledWith("/console/security");

    fireEvent.click(within(nav()).getByRole("button", { name: "Owner menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Chat" }));
    expect(onChat).toHaveBeenCalled();
  });
});
