import { cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
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
    upload: vi.fn(async () => ({
      id: "up1", file_name: "orders.csv", format: "csv" as const, size_bytes: 40,
      columns: [{ name: "id", type: "Nullable(Int64)" }, { name: "amount", type: "Nullable(Float64)" }], sample: [["1", "2.5"]],
    })),
    loadFile: vi.fn(async () => detail({ ...SHOP, id: "orders", kind: "file", host: null, port: null, database: null, user: null }, [ORDERS])),
  };
  return sources;
}

function show(sources: FitcherApi["sources"]) {
  window.localStorage.setItem("fitcher.demo.identity", "adm");
  const api = { ...createMockApi(), sources };
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{ auth: "mock", sources: "http" }}>
          <ConsoleLayout section="sources" navigate={vi.fn()} onChat={vi.fn()}><SourcesSection /></ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function fillConnection(user: ReturnType<typeof userEvent.setup>, password = "s3cret-pass") {
  await user.type(screen.getByLabelText("Name"), "erp");
  await user.type(screen.getByLabelText("Host"), "host.docker.internal");
  await user.type(screen.getByLabelText("Database"), "erp");
  await user.type(screen.getByLabelText("User"), "reader");
  await user.type(screen.getByLabelText("Password"), password);
}

describe("Sources page", () => {
  it("lists each source with its kind, address, selected tables and last sync", async () => {
    show(fakeSources());

    const row = await screen.findByRole("listitem", { name: "shop" });
    expect(within(row).getByText("PostgreSQL")).toBeTruthy();
    expect(within(row).getByText(/db\.internal:5432/)).toBeTruthy();
    expect(within(row).getByText(/1 of 3 tables/)).toBeTruthy();
    expect(within(row).getByText(/Succeeded/)).toBeTruthy();
    expect(row.textContent).not.toMatch(/password/i);
  });

  it("shows an empty state when nothing is connected", async () => {
    show(fakeSources([]));

    expect(await screen.findByText(/No source yet/)).toBeTruthy();
  });

  it("asks for the connection of the kind, with the Docker host hint and a password field", async () => {
    const user = userEvent.setup();
    show(fakeSources([]));
    await user.click(await screen.findByRole("button", { name: "Add source" }));

    expect(screen.getByLabelText("Schema")).toBeTruthy();
    expect(screen.getByText(/host\.docker\.internal/)).toBeTruthy();
    expect((screen.getByLabelText("Password") as HTMLInputElement).type).toBe("password");
    await user.selectOptions(screen.getByLabelText("Database type"), "mysql");
    expect(screen.queryByLabelText("Schema")).toBeNull();
    expect(screen.getByLabelText("TLS")).toBeTruthy();
  });

  it("tests the connection, lists the tables with sizes and the proposed mode, and connects", async () => {
    const user = userEvent.setup();
    const sources = fakeSources([]);
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Add source" }));
    await fillConnection(user);

    await user.click(screen.getByRole("button", { name: "Test connection" }));

    expect(sources.test).toHaveBeenCalledWith(expect.objectContaining({
      kind: "postgres", host: "host.docker.internal", database: "erp", user: "reader", password: "s3cret-pass", tls_mode: "prefer",
    }));
    const orders = await screen.findByRole("row", { name: /orders/ });
    expect(within(orders).getByText(/1,200/)).toBeTruthy();
    expect(within(orders).getByText(/Live/)).toBeTruthy();
    const events = screen.getByRole("row", { name: /events/ });
    expect(within(events).getByText(/Copy/)).toBeTruthy();
    expect(within(events).getByText(/above 1 million rows/)).toBeTruthy();
    expect(within(events).getByText(/Read as text: payload/)).toBeTruthy();
    expect(screen.getByText(/Estimates from the source's own statistics/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(sources.create).toHaveBeenCalledWith(expect.objectContaining({ name: "erp", password: "s3cret-pass" })));
    expect(await screen.findByRole("listitem", { name: "erp" })).toBeTruthy();
    expect(screen.queryByDisplayValue("s3cret-pass")).toBeNull();
  });

  it.each([
    ["authentication", /user or password was refused/],
    ["unreachable", /host could not be reached/],
    ["tls", /TLS settings do not match/],
    ["database_not_found", /database was not found/],
  ] as const)("shows a failed test as one fixed message for %s, never the database's own text", async (reason, message) => {
    const user = userEvent.setup();
    const sources = fakeSources([]);
    sources.test = vi.fn(async () => { throw new SourceError("The api answered 422", 422, reason); });
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Add source" }));
    await fillConnection(user);

    await user.click(screen.getByRole("button", { name: "Test connection" }));

    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("chooses tables, a mode, a refresh interval and a cursor, then saves the selection", async () => {
    const user = userEvent.setup();
    const sources = fakeSources();
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Tables of shop" }));

    const events = await screen.findByRole("row", { name: /events/ });
    await user.click(within(events).getByRole("checkbox", { name: "Use events" }));
    await user.selectOptions(within(events).getByLabelText("Refresh events"), "3600");
    await user.selectOptions(within(events).getByLabelText("Only new rows after events"), "created_at");
    await user.click(screen.getByRole("button", { name: "Save selection" }));

    await waitFor(() => expect(sources.changeTables).toHaveBeenCalled());
    const change = (sources.changeTables as ReturnType<typeof vi.fn>).mock.calls[0][1] as { tables: Record<string, unknown>[] };
    expect(change.tables.find((item) => item.name === "events")).toMatchObject({
      selected: true, mode: "copy", interval_seconds: 3600, cursor_column: "created_at",
    });
    expect(screen.getByText("Selection saved.")).toBeTruthy();
  });

  it("flags live tables joined with another live table as slow", async () => {
    const user = userEvent.setup();
    show(fakeSources());
    await user.click(await screen.findByRole("button", { name: "Tables of shop" }));

    const items = await screen.findByRole("row", { name: /items/ });

    expect(within(items).getByText(/Slow: joined with another live table/)).toBeTruthy();
  });

  it("syncs now, shows it running and lets it be cancelled", async () => {
    const user = userEvent.setup();
    const sources = fakeSources();
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Sync shop now" }));

    expect(sources.sync).toHaveBeenCalledWith("shop");
    const row = await screen.findByRole("listitem", { name: "shop" });
    await waitFor(() => expect(within(row).getByText(/Syncing/)).toBeTruthy());
    await user.click(within(row).getByRole("button", { name: "Cancel sync of shop" }));
    expect(sources.cancel).toHaveBeenCalledWith("shop");
  });

  it("shows a failed sync as its reason", async () => {
    const sources = fakeSources([{ ...SHOP, last_sync: { ...SYNC, status: "failed", error: "refused", results: [] } }]);
    show(sources);

    const row = await screen.findByRole("listitem", { name: "shop" });

    expect(within(row).getByText(/Failed/)).toBeTruthy();
    expect(within(row).getByText(/refused the connection/)).toBeTruthy();
  });

  it("replaces a password without showing the stored one", async () => {
    const user = userEvent.setup();
    const sources = fakeSources();
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Edit shop" }));

    const password = screen.getByLabelText("Password") as HTMLInputElement;
    expect(password.value).toBe("");
    expect(screen.getByText(/Leave empty to keep the stored password/)).toBeTruthy();
    await user.type(password, "new-pass");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sources.update).toHaveBeenCalledWith("shop", expect.objectContaining({ password: "new-pass" })));
  });

  it("deletes only after the name is typed and says which marts block it", async () => {
    const user = userEvent.setup();
    const sources = fakeSources();
    sources.remove = vi.fn(async () => { throw new SourceError("The api answered 409", 409, undefined, ["orders_mart"]); });
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Delete shop" }));

    const dialog = await screen.findByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Delete" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    await user.type(within(dialog).getByLabelText("Source name"), "shop");
    await user.click(confirm);

    expect(sources.remove).toHaveBeenCalledWith("shop", "shop");
    expect(await screen.findByText(/Marts still read this source: orders_mart/)).toBeTruthy();
  });

  it("uploads a file, shows the inferred types for confirmation and loads it", async () => {
    const user = userEvent.setup();
    const sources = fakeSources([]);
    show(sources);
    await user.click(await screen.findByRole("button", { name: "Add source" }));
    await user.click(screen.getByRole("tab", { name: "File" }));

    const input = screen.getByLabelText("CSV, XLSX or Parquet file") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["id,amount\n1,2.5\n"], "orders.csv", { type: "text/csv" })] } });

    await waitFor(() => expect(sources.upload).toHaveBeenCalled());
    const amount = await screen.findByLabelText("Type of amount");
    expect((amount as HTMLSelectElement).value).toBe("Nullable(Float64)");
    await user.selectOptions(amount, "Nullable(Decimal(18, 2))");
    await user.click(screen.getByRole("button", { name: "Load file" }));

    await waitFor(() => expect(sources.loadFile).toHaveBeenCalledWith("up1", {
      name: "orders", columns: [{ name: "id", type: "Nullable(Int64)" }, { name: "amount", type: "Nullable(Decimal(18, 2))" }],
    }));
  });
});
