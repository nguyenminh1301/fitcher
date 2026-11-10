import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createApi } from "@/lib/api";
import { createMockApi } from "@/lib/api/mock";
import { httpApi } from "@/lib/api/http";
import { FEATURES, type Sources } from "@/lib/api/sources";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
import { I18nProvider } from "@/lib/i18n/react";

const CONSOLE = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst", "marketing"],
  identities: [{ user_id: "u1", display_name: "Ana", roles: ["analyst", "admin"] }],
  conversations: [],
  datasets: [{ id: "orders", description: "Orders.", grain: "one row per order", time_column: "day", readable_roles: ["analyst"], columns: [] }],
  review_items: [],
  documents: [],
  feedback: [],
  eval_reports: [],
  runs: [],
  traces: {},
  audit: [],
  costs: [],
  users: [{ id: "u2", username: "lab.marketing", display_name: "Lab Marketing", roles: ["marketing"], enabled: true }],
};

function fakeFetch(files: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    const name = url.split("/").pop() as string;
    return name in files ? new Response(JSON.stringify(files[name])) : new Response(JSON.stringify({ error: "sample_data_missing" }), { status: 404 });
  });
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("takes each feature from the source sources.ts names", () => {
    const mock = createMockApi();
    const sources = Object.fromEntries(FEATURES.map((feature) => [feature, "mock"])) as Sources;
    sources.chat = "http";

    const api = createApi(sources, mock, httpApi);

    expect(api.chat).toBe(httpApi.chat);
    expect(api.datasets).toBe(mock.datasets);
  });

  it("missing sample data yields empty lists, not an exception", async () => {
    vi.stubGlobal("fetch", fakeFetch({}));
    const mock = createMockApi();

    expect(await mock.datasets.list()).toEqual([]);
    expect(await mock.sampleStatus()).toBe("missing");
  });

  it("console actions change the sample state", async () => {
    vi.stubGlobal("fetch", fakeFetch({ console: CONSOLE, scenarios: { suggestions: [], scenarios: [] } }));
    const mock = createMockApi();

    await mock.users.setRoles("u2", ["analyst"]);
    await mock.users.setEnabled("u2", false);

    expect(await mock.users.list()).toEqual([{ ...CONSOLE.users[0], roles: ["analyst"], enabled: false }]);
    expect(await mock.datasets.list()).toEqual(CONSOLE.datasets);
  });
});

describe("sample data badge", () => {
  it("shows for a feature on sample data and not for a wired one", () => {
    render(
      <I18nProvider>
        <SampleDataBadge feature="datasets" sources={{ datasets: "mock" }} />
        <SampleDataBadge feature="chat" sources={{ chat: "http" }} />
      </I18nProvider>,
    );

    expect(screen.getAllByText("Sample data")).toHaveLength(1);
  });
});
