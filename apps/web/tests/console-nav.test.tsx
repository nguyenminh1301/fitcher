import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { areaOf, AREAS, sectionOf, SECTIONS } from "@/lib/console/sections";
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

function renderConsole(user: string, section: string, api = createMockApi()) {
  window.localStorage.setItem("fitcher.demo.identity", user);
  const navigate = vi.fn();
  const onChat = vi.fn();
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{}}>
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
  it("puts every page in one of six areas, with the Overview first", () => {
    expect(AREAS.map((area) => area.key)).toEqual(["overview", "sources", "documents", "quality", "activity", "settings"]);
    expect(AREAS.flatMap((area) => area.pages).sort()).toEqual(SECTIONS.map((section) => section.key).sort());
    expect(areaOf("datasets").key).toBe("sources");
    expect(areaOf("audit").key).toBe("activity");
    expect(sectionOf("/console")).toBe("overview");
    expect(sectionOf("/console/runs/abc")).toBe("runs");
  });
});

describe("console layout", () => {
  it("shows six areas, with the area of the open page current", async () => {
    renderConsole("rev", "feedback");

    await waitFor(() => expect(links()).toEqual(["Overview", "Sources", "Documents", "Quality", "Activity", "Settings", "Chat"]));
    expect(within(nav()).getByRole("link", { name: "Quality" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav()).getByRole("link", { name: "Quality" }).getAttribute("href")).toBe("/console/review");
    expect(screen.getByText("section page")).toBeTruthy();
  });

  it("names the current source at the top, and its menu chooses another one for every page", async () => {
    const api = createMockApi();
    Object.assign(api.sources, { list: vi.fn(async () => [
      { id: "shop", kind: "postgres", pack: { name: "shop", status: "ready", datasets: 2, error: null } },
      { id: "crm", kind: "file", pack: { name: "crm", status: "ready", datasets: 1, error: null } },
    ]) });
    const choose = vi.spyOn(api.auth, "choosePack").mockResolvedValue({ name: "crm", display_name: "Crm", roles: ["analyst"] });
    const { navigate } = renderConsole("rev", "overview", api);

    fireEvent.click(await within(nav()).findByRole("button", { name: "Source: shop. Choose another" }));
    const menu = await screen.findByRole("menu");
    await act(async () => fireEvent.click(within(menu).getByRole("menuitem", { name: /crm/ })));
    expect(choose).toHaveBeenCalledWith("crm");
    expect(await within(nav()).findByRole("button", { name: "Source: crm. Choose another" })).toBeTruthy();

    fireEvent.click(within(nav()).getByRole("button", { name: "Source: crm. Choose another" }));
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "Manage sources" }));
    expect(navigate).toHaveBeenCalledWith("/console/sources");
  });

  it("opens the navigation as a drawer and closes it after a page is picked", async () => {
    const { navigate } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Activity"));
    const app = document.querySelector(".cs");

    fireEvent.click(screen.getByRole("button", { name: "Open the menu" }));
    expect(app?.getAttribute("data-drawer")).toBe("open");
    fireEvent.click(within(nav()).getByRole("link", { name: "Activity" }));

    expect(navigate).toHaveBeenCalledWith("/console/runs");
    expect(app?.getAttribute("data-drawer")).toBe("closed");
  });

  it("offers sign-out once a password is set on this page, without reloading", async () => {
    const api = createMockApi();
    const status = vi.spyOn(api.owner, "status").mockResolvedValue({ password_set: false, signed_in: false, exposed: false } as never);
    renderConsole("rev", "review", api);
    await waitFor(() => expect(links()).toContain("Quality"));
    status.mockResolvedValue({ password_set: true, signed_in: true, exposed: false } as never);

    fireEvent.click(await within(nav()).findByRole("button", { name: "Owner menu" }));

    expect(await screen.findByRole("menuitem", { name: "Sign out" })).toBeTruthy();
  });

  it("offers the chat and the Security page from the owner menu, and no sign-out without a password", async () => {
    const { onChat, navigate } = renderConsole("rev", "review");
    await waitFor(() => expect(links()).toContain("Quality"));

    fireEvent.click(await within(nav()).findByRole("button", { name: "Owner menu" }));
    expect(screen.getByRole("radiogroup", { name: "Theme" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Sign out" })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Security" }));
    expect(navigate).toHaveBeenCalledWith("/console/security");

    fireEvent.click(within(nav()).getByRole("button", { name: "Owner menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Chat" }));
    expect(onChat).toHaveBeenCalled();
  });
});

describe("area tabs", () => {
  it("shows the pages of the open page's area as tabs, the open one current", async () => {
    const { AreaTabs } = await import("@/components/console/ListPage");
    const navigate = vi.fn();
    render(
      <ThemeProvider>
        <I18nProvider initial="en">
          <ChatProvider api={createMockApi()} navigate={vi.fn()} activeId={null} sources={{}}>
            <ConsoleLayout section="costs" navigate={navigate} onChat={vi.fn()}><AreaTabs section="costs" /></ConsoleLayout>
          </ChatProvider>
        </I18nProvider>
      </ThemeProvider>,
    );

    const tabs = await screen.findByRole("navigation", { name: "Activity" });
    expect(within(tabs).getAllByRole("link").map((link) => link.textContent)).toEqual(["Runs", "Query log", "Costs"]);
    expect(within(tabs).getByRole("link", { name: "Costs" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(within(tabs).getByRole("link", { name: "Query log" }));
    expect(navigate).toHaveBeenCalledWith("/console/audit");
  });
});
