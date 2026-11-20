import { cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { AddSourcePage, BuildPackPage } from "@/components/console/sections/SourceFlows";
import { SourcesSection } from "@/components/console/sections/SourcesSection";
import type { FitcherApi } from "@/lib/api/client";
import { SourceError } from "@/lib/api/http/sources";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import type { SourceDetail, SourceView, SyncView, TableView } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

configure({ asyncUtilTimeout: 4000 });

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst"],
  identities: [{ user_id: "adm", display_name: "Ada Admin", roles: ["admin", "analyst"] }],
  conversations: [],
};

const SYNC: SyncView = {
  id: 1, status: "succeeded", started_by: "schedule", started_at: "2026-11-14T08:00:00Z", finished_at: "2026-11-14T08:00:05Z",
  results: [{ table: "orders", mode: "copy", rows: 1200, full: true }], error: null,
};

function table(changes: Partial<TableView>): TableView {
  return {
    name: "orders", kind: "table", rows: 1200, size_bytes: 400_000, columns: [{ name: "id", type: "integer", nullable: false }],
    primary_key: ["id"], foreign_keys: [], unusual_columns: [], selected: false, mode: "live", proposed_mode: "live", reason: "small",
    slow: false, interval_seconds: 86_400, cursor_column: null, cursor_candidates: ["id", "created_at"], last_synced_at: null,
    last_rows: null, next_run_at: null, ...changes,
  };
}

const ORDERS = table({});
const BIG = table({ name: "events", rows: 9_000_000, size_bytes: 2 * 1024 ** 3, mode: "copy", proposed_mode: "copy", reason: "rows", unusual_columns: ["payload"] });
const LINKED = table({ name: "items", slow: true, selected: true });

const SHOP: SourceView = {
  id: "shop", kind: "postgres", host: "db.internal", port: 5432, database: "erp", schema_name: "public", user: "reader",
  tls_mode: "prefer", has_ca: false, created_at: "2026-11-01T08:00:00Z", table_count: 3, selected_count: 1, last_sync: SYNC,
};

function detail(view: SourceView, tables: TableView[]): SourceDetail {
  return { ...view, tables };
}

function fakeSources(initial: SourceView[] = [SHOP]) {
  let list = initial;
  const sources: FitcherApi["sources"] = {
    list: vi.fn(async () => list),
    test: vi.fn(async () => ({ tables: [ORDERS, BIG] })),
    create: vi.fn(async (body) => {
      const created = { ...SHOP, id: body.name, table_count: 2, selected_count: 0, last_sync: null };
      list = [...list, created];
      return detail(created, [ORDERS, BIG]);
    }),
    update: vi.fn(async () => detail(SHOP, [ORDERS])),
    remove: vi.fn(async () => undefined),
    tables: vi.fn(async () => [ORDERS, BIG, LINKED]),
    changeTables: vi.fn(async () => [ORDERS, BIG, LINKED]),
    sync: vi.fn(async () => ({ ...SYNC, id: 2, status: "running" as const, finished_at: null, results: [] })),
    cancel: vi.fn(async () => SYNC),
    syncs: vi.fn(async () => [SYNC]),
    drift: vi.fn(async () => ({ pack: null, changes: [] })),
    instantEstimate: vi.fn(async () => ({ prompt_tokens: 3000, datasets: 2, model_missing: null })),
    instantStart: vi.fn(async () => { throw new Error("not started in this test"); }),
    instantJob: vi.fn(async () => { throw new Error("no job in this test"); }),
    upload: vi.fn(async () => ({
      id: "up1", file_name: "orders.csv", format: "csv" as const, size_bytes: 40,
      columns: [{ name: "id", type: "Nullable(Int64)" }, { name: "amount", type: "Nullable(Float64)" }], sample: [["1", "2.5"]],
    })),
    loadFile: vi.fn(async () => detail({ ...SHOP, id: "orders", kind: "file", host: null, port: null, database: null, user: null }, [ORDERS])),
  };
  return sources;
}

let navigate = vi.fn();

let choose: Mock<FitcherApi["auth"]["choosePack"]>;

function show(sources: FitcherApi["sources"], page: React.ReactNode = <SourcesSection />) {
  window.localStorage.setItem("fitcher.demo.identity", "adm");
  const base = createMockApi();
  choose = vi.fn(async (name: string) => ({ name, display_name: name, roles: ["analyst"] }));
  const api = { ...base, sources, auth: { ...base.auth, choosePack: choose } };
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{ auth: "mock", sources: "http" }}>
          <ConsoleLayout section="sources" navigate={navigate} onChat={vi.fn()}>{page}</ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  navigate = vi.fn();
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const row = async (name: string) => (await screen.findByRole("row", { name })) as HTMLElement;

describe("Sources page", () => {
  it("lists each source with its kind, tables in use, last sync and status", async () => {
    show(fakeSources());
    const shop = await row("shop");

    expect(within(shop).getByText("PostgreSQL")).toBeTruthy();
    expect(within(shop).getByRole("button", { name: "Tables of shop" }).textContent).toBe("1 of 3 tables");
    expect(within(shop).getByText(/1,200 rows/)).toBeTruthy();
    expect(within(shop).getByText("Succeeded")).toBeTruthy();
  });

  it("says whether each source can answer questions, builds the ones that cannot and asks the ready ones", async () => {
    const ready = { ...SHOP, id: "ready_shop", pack: { name: "ready_shop", status: "ready" as const, datasets: 3, error: null } };
    const missing = { ...SHOP, id: "new_shop", pack: { name: "new_shop", status: "none" as const, datasets: 0, error: null } };
    const unsynced = { ...SHOP, id: "empty_shop", last_sync: null, pack: null };
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    show(fakeSources([ready, missing, unsynced]));

    expect(within(await row("ready_shop")).getByText("Ready")).toBeTruthy();
    expect(within(await row("new_shop")).getByText("Not ready for questions")).toBeTruthy();
    expect((within(await row("empty_shop")).getByRole("button", { name: "Get empty_shop ready for questions" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(within(await row("new_shop")).getByRole("button", { name: "Get new_shop ready for questions" }));
    expect(navigate).toHaveBeenCalledWith("/console/sources/new_shop/pack");

    fireEvent.click(within(await row("ready_shop")).getByRole("button", { name: "Ask about ready_shop" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(choose).toHaveBeenCalledWith("ready_shop");
  });

  it("reads a building pack again until it ends, and shows why it failed", async () => {
    const building = { ...SHOP, pack: { name: "shop", status: "building" as const, datasets: 0, error: null } };
    const failed = { ...SHOP, pack: { name: "shop", status: "failed" as const, datasets: 0, error: "embedding limit is used up" } };
    const sources = fakeSources();
    sources.list = vi.fn().mockResolvedValueOnce([building]).mockResolvedValue([failed]);
    show(sources);
    expect(within(await row("shop")).getByText("Getting ready…")).toBeTruthy();

    expect(await within(await row("shop")).findByText("embedding limit is used up", {}, { timeout: 5000 })).toBeTruthy();
    expect(within(await row("shop")).getByText("Could not get ready")).toBeTruthy();
  });

  it("shows an empty state with a way to add a source", async () => {
    show(fakeSources([]));
    expect(await screen.findByText("No source yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    const dialog = screen.getByRole("dialog", { name: "Add a data source" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Connect a database/ }));
    expect(navigate).toHaveBeenCalledWith("/console/sources/new?kind=database");
  });

  it("chooses tables, a mode, a refresh interval and a new-rows column, then saves and prepares them", async () => {
    const sources = fakeSources();
    show(sources);
    fireEvent.click(within(await row("shop")).getByRole("button", { name: "Tables of shop" }));
    const dialog = await screen.findByRole("dialog", { name: "Tables of shop" });

    await within(dialog).findByText("events");
    expect(within(dialog).getByText("Proposed: Copy, because above 1 million rows")).toBeTruthy();
    expect(within(dialog).getByText("payload")).toBeTruthy();
    expect(within(dialog).getByText("Slow: joined with another live table")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Use events" }));
    fireEvent.change(within(dialog).getByRole("combobox", { name: "Refresh events" }), { target: { value: "3600" } });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "New rows only for events" }), { target: { value: "created_at" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save the choice" }));

    await waitFor(() => expect(sources.changeTables).toHaveBeenCalled());
    const change = (sources.changeTables as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(change.tables.find((item: { name: string }) => item.name === "events")).toEqual({
      name: "events", selected: true, mode: "copy", interval_seconds: 3600, cursor_column: "created_at",
    });
    expect(sources.sync).toHaveBeenCalledWith("shop");
    expect(await within(dialog).findByText("Saved. Preparing the tables…")).toBeTruthy();
  });

  it("shows what changed since the pack was built and opens the rebuild", async () => {
    const sources = fakeSources();
    sources.drift = vi.fn(async () => ({ pack: "shop", changes: [
      { table: "orders", added: ["note_text"], removed: ["coupon"], retyped: [], missing: false },
      { table: "returns", added: [], removed: [], retyped: [], missing: true },
    ] }));
    show(sources);

    const banner = (await screen.findByText("The pack shop no longer matches source shop.")).closest(".fc-banner") as HTMLElement;
    expect(banner.textContent).toContain("orders: added note_text, removed coupon");
    expect(banner.textContent).toContain("returns: no longer in the source");
    fireEvent.click(within(banner).getByRole("button", { name: "Rebuild the pack of shop" }));
    expect(navigate).toHaveBeenCalledWith("/console/sources/shop/pack");
  });

  it("syncs now, shows a running sync with a way to cancel it, and a failed one with its reason", async () => {
    const sources = fakeSources([
      SHOP,
      { ...SHOP, id: "kho", last_sync: { ...SYNC, status: "running", finished_at: null } },
      { ...SHOP, id: "crm", last_sync: { ...SYNC, status: "failed", error: "refused" } },
    ]);
    show(sources);

    fireEvent.click(within(await row("shop")).getByRole("button", { name: "Sync shop now" }));
    await waitFor(() => expect(sources.sync).toHaveBeenCalledWith("shop"));
    fireEvent.click(within(await row("kho")).getByRole("button", { name: "Cancel sync of kho" }));
    await waitFor(() => expect(sources.cancel).toHaveBeenCalledWith("kho"));
    const crm = await row("crm");
    expect(within(crm).getByText(/refused the connection/)).toBeTruthy();
    expect(within(crm).getByRole("button", { name: "Sync crm now" }).textContent).toContain("Retry");
  });

  it("shows a retried sync as syncing until the list has its outcome, then the new status without a reload", async () => {
    const failed = { ...SHOP, last_sync: { ...SYNC, status: "failed" as const, error: "refused" as const } };
    const sources = fakeSources([failed]);
    // The first read after the retry still returns the old failed sync; the next returns the retry's success.
    vi.mocked(sources.list)
      .mockResolvedValueOnce([failed])
      .mockResolvedValueOnce([failed])
      .mockResolvedValue([{ ...SHOP, last_sync: { ...SYNC, id: 2, status: "succeeded" as const } }]);
    show(sources);

    fireEvent.click(within(await row("shop")).getByRole("button", { name: "Sync shop now" }));

    await waitFor(() => expect(within(screen.getByRole("row", { name: "shop" })).getAllByText("Syncing").length).toBeGreaterThan(0));
    expect(within(screen.getByRole("row", { name: "shop" })).queryByText("Failed")).toBeNull();
    await waitFor(() => expect(within(screen.getByRole("row", { name: "shop" })).getByText("Succeeded")).toBeTruthy(), { timeout: 5000 });
  });

  it("names each table a partial sync could not read with its reason", async () => {
    const partial = { ...SHOP, last_sync: { ...SYNC, status: "partial" as const, error: "unsupported_name" as const, results: [
      { table: "orders", mode: "live", rows: 3, full: null },
      { table: "it's", mode: "live", rows: null, full: null, error: "unsupported_name" },
    ] } };
    show(fakeSources([partial]));

    const shop = await row("shop");
    expect(within(shop).getByText("Partly synced")).toBeTruthy();
    expect(within(shop).getByText("1 table could not be read:")).toBeTruthy();
    expect(within(shop).getByText("it's").closest("li")?.textContent).toContain("name or a column name has a quote");
    expect(within(shop).queryByText(/failed for another reason/)).toBeNull();
  });

  it("edits a connection and keeps the stored password when the field is left empty", async () => {
    const sources = fakeSources();
    show(sources);
    fireEvent.click(within(await row("shop")).getByRole("button", { name: "Edit shop" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit shop" });

    expect((within(dialog).getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(within(dialog).getByText("Leave empty to keep the stored password.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Host"), { target: { value: "db2.internal" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sources.update).toHaveBeenCalledWith("shop", expect.objectContaining({ host: "db2.internal" })));
    expect((sources.update as ReturnType<typeof vi.fn>).mock.calls[0][1]).not.toHaveProperty("password");
  });

  it("deletes only after the name is typed and says which analysis tables block it", async () => {
    const sources = fakeSources();
    sources.remove = vi.fn(async () => { throw new SourceError("in use", 409, undefined, ["orders_mart"]); });
    show(sources);
    fireEvent.click(within(await row("shop")).getByRole("button", { name: "Options for shop" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete shop?" });

    const remove = within(dialog).getByRole("button", { name: "Delete" });
    expect(remove.hasAttribute("disabled")).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("Source name"), { target: { value: "shop" } });
    fireEvent.click(remove);

    expect(await within(dialog).findByText(/still read this source/)).toBeTruthy();
    expect(sources.remove).toHaveBeenCalledWith("shop", "shop");
  });

  it("offers only the copy mode for the tables of a SQL Server source", async () => {
    show(fakeSources([{ ...SHOP, kind: "sqlserver" }]));
    fireEvent.click(within(await row("shop")).getByRole("button", { name: "Tables of shop" }));
    const dialog = await screen.findByRole("dialog", { name: "Tables of shop" });
    const mode = (await within(dialog).findByRole("combobox", { name: "How orders is read" })) as HTMLSelectElement;

    expect([...mode.options].map((option) => option.value)).toEqual(["copy"]);
  });
});

describe("Source flows", () => {
  it("adds a database from its own page with the setup's form and builds its pack", async () => {
    const sources = fakeSources();
    show(sources, <AddSourcePage kind="database" />);

    fireEvent.change(await screen.findByLabelText("Host"), { target: { value: "db" } });
    fireEvent.change(screen.getByLabelText("Database"), { target: { value: "erp" } });
    fireEvent.change(screen.getByLabelText("User"), { target: { value: "reader" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Check the connection" }));
    fireEvent.click(await screen.findByRole("button", { name: "Choose tables" }));
    expect(sources.create).toHaveBeenCalledWith(expect.objectContaining({ name: "erp" }));
    fireEvent.click(await screen.findByRole("button", { name: /Use 2 tables/ }));

    // The saved choice comes back from the api; here it keeps one chosen table.
    expect(await screen.findByRole("heading", { name: "Build the pack from 1 table" })).toBeTruthy();
  });

  it("rebuilds a source's pack from the tables in use", async () => {
    const sources = fakeSources();
    show(sources, <BuildPackPage id="shop" />);

    expect(await screen.findByRole("heading", { name: "Build the pack from 1 table" })).toBeTruthy();
    await waitFor(() => expect(sources.instantEstimate).toHaveBeenCalledWith({ source_id: "shop", tables: ["items"] }));
  });
});
