import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TableChooser } from "@/components/sources/TableChooser";
import type { FitcherApi } from "@/lib/api/client";
import type { TableView } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";

afterEach(cleanup);

function tables(count: number): TableView[] {
  return Array.from({ length: count }, (_, index) => ({
    name: `t${index}`, kind: "table", rows: 10, size_bytes: 100, columns: [], primary_key: [], foreign_keys: [], unusual_columns: [],
    selected: false, mode: "live", proposed_mode: "live", reason: "small", slow: false, interval_seconds: 86_400, cursor_column: null,
    cursor_candidates: [], last_synced_at: null, last_rows: null, next_run_at: null,
  }));
}

function show(count: number) {
  render(<I18nProvider initial="en"><TableChooser sources={{} as FitcherApi["sources"]} id="erp" tables={tables(count)} preselect /></I18nProvider>);
}

describe("table chooser in the setup", () => {
  it("preselects every table of a source with at most 20", () => {
    show(20);

    expect(screen.getAllByRole("checkbox").every((box) => (box as HTMLInputElement).checked)).toBe(true);
  });

  it("preselects none above 20 and warns above 50", () => {
    show(51);

    expect(screen.getAllByRole("checkbox").some((box) => (box as HTMLInputElement).checked)).toBe(false);
    expect(screen.getByText(/51 tables/)).toBeTruthy();
  });

  it("does not warn between 21 and 50 tables", () => {
    show(30);

    expect(screen.queryByText(/30 tables/)).toBeNull();
  });
});
