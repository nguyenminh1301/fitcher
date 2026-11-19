import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SetupGate } from "@/components/setup/SetupGate";
import { SetupScreen } from "@/components/setup/SetupScreen";
import type { FitcherApi } from "@/lib/api/client";
import type { ModelTiersView, ProviderView, SetupStatus } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

afterEach(cleanup);

const NEW: SetupStatus = {
  steps: [{ id: "models", state: "pending" }, { id: "data", state: "pending" }], complete: false,
};
const ANSWERED: SetupStatus = {
  steps: [{ id: "models", state: "done" }, { id: "data", state: "skipped" }], complete: false,
};

function fakeSetup(initial: SetupStatus = NEW) {
  let status = initial;
  const setup: FitcherApi["setup"] = {
    status: vi.fn(async () => status),
    skip: vi.fn(async () => status),
    complete: vi.fn(async () => (status = { ...status, complete: true })),
  };
  return setup;
}

const OPENAI: ProviderView = {
  id: "openai", name: "OpenAI", kind: "openai", base_url: null, key_set: true, key_last4: "7777", hosted: true, in_use: true,
};
const PROPOSED: ModelTiersView = {
  tiers: [
    { tier: "fast", provider_id: "openai", model: "gpt-5.4-mini", eval: null },
    { tier: "sql-gen", provider_id: "openai", model: "gpt-5.4", eval: null },
  ],
  embedding: { backend: "local", provider_id: null, model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", dimensions: 384, needs_reindex: false },
};

function fakeModels() {
  return {
    providers: vi.fn(async () => [OPENAI]),
    addProvider: vi.fn(async () => OPENAI),
    testProvider: vi.fn(async () => ({
      provider_id: "openai", models: ["gpt-5.4", "gpt-5.4-mini"], model: "gpt-5.4-mini", structured_output: true, paid: true, error: null,
    })),
    tiers: vi.fn(async () => PROPOSED),
  } as unknown as FitcherApi["models"];
}

const noSources = { list: vi.fn(async () => []) } as unknown as FitcherApi["sources"];

/** The ways out of the setup and the pack check, as spies. */
function exits(pack = false) {
  return { hasPack: vi.fn(async () => pack), onOpenChat: vi.fn(), onOpenConsole: vi.fn() };
}

function wrap(node: React.ReactNode) {
  return render(<ThemeProvider><I18nProvider initial="en">{node}</I18nProvider></ThemeProvider>);
}

describe("setup screen", () => {
  it("shows a bar per step, Model, Data and Start, with the current one marked", async () => {
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={fakeSetup()} {...exits()} />);
    const steps = await screen.findByRole("list", { name: "Setup progress" });
    expect(within(steps).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Step 1: Model", "Step 2: Data", "Step 3: Start"]);
    expect(within(steps).getAllByRole("listitem")[0].getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
  });

  it("lists what is still missing once the steps were left for later, and finishing opens the console", async () => {
    const setup = fakeSetup(ANSWERED);
    const ways = exits();
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={setup} {...ways} />);

    expect(await screen.findByRole("heading", { name: "2 things left before you can ask" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /No data yet/ }).getAttribute("href")).toBe("/console/sources");
    expect(screen.getByText("No pack yet")).toBeTruthy();
    expect(screen.queryByText("No model yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(ways.onOpenConsole).toHaveBeenCalled());
    expect(setup.complete).toHaveBeenCalled();
  });

  it("opens an answered step again from its bar", async () => {
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={fakeSetup(ANSWERED)} {...exits()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Open the Model step again" }));
    expect(await screen.findByText("Choose the model that answers questions")).toBeTruthy();
  });

});

describe("setup models step", () => {
  const MODELS_PENDING: SetupStatus = {
    steps: [{ id: "models", state: "pending" }], complete: false,
  };

  it("checks a key in one go, says the check is billed, and shows the model chosen for each task", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={setup} models={models} {...exits()} />);

    expect(await screen.findByText("The check sends one small request to OpenAI, and OpenAI bills it.")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /OpenAI/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("link", { name: /Get a key from OpenAI/ }).getAttribute("href")).toBe("https://platform.openai.com/api-keys");
    await userEvent.type(screen.getByLabelText("API key"), "sk-test-0000-7777");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));

    expect(models.addProvider).toHaveBeenCalledWith({ kind: "openai", api_key: "sk-test-0000-7777" });
    expect(models.testProvider).toHaveBeenCalledWith("openai");
    expect(await screen.findByRole("heading", { name: "OpenAI is connected" })).toBeTruthy();
    const table = screen.getByRole("table", { name: "Model for each kind of task" });
    expect(table.textContent).toContain("gpt-5.4");
    await userEvent.click(screen.getByRole("button", { name: "Go to the Data step" }));
    await waitFor(() => expect(setup.status).toHaveBeenCalledTimes(2));
  });

  it("removes the provider again when the check fails and says why under the key", async () => {
    const models = {
      ...fakeModels(),
      testProvider: vi.fn(async () => ({ provider_id: "openai", models: [], model: null, structured_output: false, paid: true, error: "The key was refused." })),
      removeProvider: vi.fn(async () => undefined),
    } as unknown as FitcherApi["models"];
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.type(await screen.findByLabelText("API key"), "sk-wrong");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));

    expect((await screen.findByRole("alert")).textContent).toBe("The check failed: The key was refused.");
    expect(models.removeProvider).toHaveBeenCalledWith("openai");
    expect(screen.getByLabelText("API key").getAttribute("aria-invalid")).toBe("true");
  });

  it("removes the provider and goes back to the list when the provider is changed", async () => {
    const models = { ...fakeModels(), removeProvider: vi.fn(async () => undefined) } as unknown as FitcherApi["models"];
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.type(await screen.findByLabelText("API key"), "sk-test");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));
    await userEvent.click(await screen.findByRole("button", { name: "Change provider" }));

    expect(models.removeProvider).toHaveBeenCalledWith("openai");
    expect(await screen.findByRole("radiogroup", { name: "Provider" })).toBeTruthy();
  });

  it("suggests a model server's usual address with the Docker hint, takes no key and says nothing is billed", async () => {
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.click(await screen.findByRole("radio", { name: /Ollama on this computer/ }));

    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(screen.queryByText(/bills it/)).toBeNull();
    expect(screen.getByText(/host\.docker\.internal\./)).toBeTruthy();
    const address = screen.getByLabelText("Address");
    expect((address as HTMLInputElement).value).toBe("http://host.docker.internal:11434");
    await userEvent.clear(address);
    await userEvent.type(address, "http://192.168.1.20:11434");
    await userEvent.click(screen.getByRole("button", { name: "Check the connection" }));
    expect(models.addProvider).toHaveBeenCalledWith({ kind: "ollama", base_url: "http://192.168.1.20:11434" });
  });

  it("asks a name for any other OpenAI-compatible endpoint and sends it", async () => {
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.click(await screen.findByRole("button", { name: "More providers" }));
    await userEvent.click(screen.getByRole("radio", { name: /Other OpenAI-compatible endpoint/ }));
    await userEvent.type(screen.getByLabelText("Address"), "https://llm.example.test/v1");
    const check = screen.getByRole("button", { name: /Check the/ }) as HTMLButtonElement;
    expect(check.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Name"), "Company server");
    await userEvent.click(check);
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "Company server", base_url: "https://llm.example.test/v1",
    });
  });

  it("lists more providers by group, and adds a service from its preset with no address to type", async () => {
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.click(await screen.findByRole("button", { name: "More providers" }));
    expect(screen.getByRole("group", { name: "Model services" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "On this computer" })).toBeTruthy();
    await userEvent.click(screen.getByRole("radio", { name: /Groq/ }));

    expect(screen.queryByLabelText("Address")).toBeNull();
    expect(screen.getByRole("link", { name: /Get a key from Groq/ }).getAttribute("href")).toBe("https://console.groq.com/keys");
    await userEvent.type(screen.getByLabelText("API key"), "gsk-test-1234");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "Groq", api_key: "gsk-test-1234", base_url: "https://api.groq.com/openai/v1",
    });
  });

  it("offers Z.ai as a model service with its fixed endpoint and key page", async () => {
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.click(await screen.findByRole("button", { name: "More providers" }));
    await userEvent.click(within(screen.getByRole("group", { name: "Model services" })).getByRole("radio", { name: /Z\.ai/ }));

    expect(screen.queryByLabelText("Address")).toBeNull();
    expect(screen.getByRole("link", { name: /Get a key from Z\.ai/ }).getAttribute("href")).toBe("https://z.ai/manage-apikey/apikey-list");
    await userEvent.type(screen.getByLabelText("API key"), "zai-test-1234");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "Z.ai", api_key: "zai-test-1234", base_url: "https://api.z.ai/api/paas/v4",
    });
  });

  it("shows OpenRouter's free-model note, then maps every tier to the chosen free model and checks it", async () => {
    const OPENROUTER: ProviderView = {
      id: "openai-compatible", name: "OpenRouter", kind: "openai_compatible", base_url: "https://openrouter.ai/api/v1",
      key_set: true, key_last4: "abcd", hosted: false, in_use: false,
    };
    const unmapped: ModelTiersView = {
      tiers: ["fast", "sql-small", "sql-gen", "sql-gen-hard"].map((tier) => ({ tier, provider_id: null, model: null, eval: null })),
      embedding: PROPOSED.embedding,
    };
    const models = {
      addProvider: vi.fn(async () => OPENROUTER),
      tiers: vi.fn(async () => unmapped),
      providerModels: vi.fn(async () => ({
        provider_id: OPENROUTER.id, models: ["openai/gpt-5.4", "nvidia/nemotron-3-ultra-550b-a55b:free", "qwen/qwen3-coder:free"],
      })),
      setTier: vi.fn(async () => unmapped),
      testProvider: vi.fn(async () => ({ provider_id: OPENROUTER.id, models: ["qwen/qwen3-coder:free"], model: "qwen/qwen3-coder:free", structured_output: true, paid: false, error: null })),
    } as unknown as FitcherApi["models"];
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} {...exits()} />);

    await userEvent.click(await screen.findByRole("radio", { name: /OpenRouter/ }));
    expect(screen.queryByText(/bills it/)).toBeNull();
    expect(screen.getByText(/ends in :free cost nothing/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("API key"), "sk-or-v1-test");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "OpenRouter", api_key: "sk-or-v1-test", base_url: "https://openrouter.ai/api/v1",
    });

    const list = await screen.findByRole("radiogroup", { name: "Model" });
    expect(screen.getByText("2 of 3 models")).toBeTruthy();
    expect(list.textContent).not.toContain("openai/gpt-5.4");
    await userEvent.click(screen.getByRole("button", { name: /Free models only/ }));
    expect(screen.getByText("3 of 3 models")).toBeTruthy();
    await userEvent.click(within(screen.getByRole("radiogroup", { name: "Model" })).getByRole("radio", { name: "qwen/qwen3-coder:free" }));
    await userEvent.click(screen.getByRole("button", { name: "Use this model" }));

    await waitFor(() => expect(models.setTier).toHaveBeenCalledTimes(4));
    expect(models.setTier).toHaveBeenCalledWith("sql-gen-hard", { provider_id: OPENROUTER.id, model: "qwen/qwen3-coder:free" });
    expect(models.testProvider).toHaveBeenCalledWith(OPENROUTER.id, "qwen/qwen3-coder:free");
    expect(await screen.findByRole("heading", { name: "OpenRouter is connected" })).toBeTruthy();
  });

  it("can be left for later", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    wrap(<SetupScreen sources={noSources} setup={setup} models={fakeModels()} {...exits()} />);

    await userEvent.click(await screen.findByRole("button", { name: "Later" }));

    expect(setup.skip).toHaveBeenCalledWith("models");
  });
});

describe("setup gate", () => {
  const gateApi = (setup: FitcherApi["setup"]) => ({ setup }) as unknown as Pick<FitcherApi, "setup">;

  it("sends an unfinished instance to /setup and shows nothing", async () => {
    const redirect = vi.fn();
    wrap(<SetupGate api={gateApi(fakeSetup())} redirect={redirect}>app</SetupGate>);
    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/setup"));
    expect(screen.queryByText("app")).toBeNull();
  });

  it("opens the app once setup is complete", async () => {
    const done: SetupStatus = { steps: [{ id: "models", state: "done" }], complete: true };
    wrap(<SetupGate api={gateApi(fakeSetup(done))} redirect={() => {}}>app</SetupGate>);
    expect(await screen.findByText("app")).toBeTruthy();
  });

  it("opens the app when the status cannot be read", async () => {
    const setup = fakeSetup();
    setup.status = vi.fn(async () => { throw new Error("down"); });
    wrap(<SetupGate api={gateApi(setup)} redirect={() => {}}>app</SetupGate>);
    expect(await screen.findByText("app")).toBeTruthy();
  });
});

describe("setup data and start steps", () => {
  const DATA_PENDING: SetupStatus = {
    steps: [{ id: "models", state: "done" }, { id: "data", state: "pending" }],
    complete: false,
  };
  const TABLE = {
    name: "orders", kind: "table" as const, rows: 10, size_bytes: 2048, columns: [{ name: "id", type: "integer", nullable: false }],
    primary_key: ["id"], foreign_keys: [], unusual_columns: [], selected: false, mode: "copy" as const, proposed_mode: "copy" as const,
    reason: "rows", slow: false, interval_seconds: 86_400, cursor_column: null, cursor_candidates: ["id"], last_synced_at: null,
    last_rows: null, next_run_at: null,
  };
  const CREATED = {
    id: "erp", kind: "postgres" as const, host: "db", port: 5432, database: "erp", schema_name: "public", user: "reader",
    tls_mode: "prefer" as const, has_ca: false, created_at: "2026-11-14T08:00:00Z", table_count: 1, selected_count: 0, last_sync: null,
    tables: [TABLE],
  };
  const JOB = (status: "running" | "succeeded" | "failed", steps: Record<string, string>) => ({
    id: "j1", source_id: "erp", tables: ["orders"], status,
    steps: ["marts", "profile", "files", "draft", "approve", "compile", "activate"].map((id) => ({ id, state: steps[id] ?? "pending" })),
    failed_step: status === "failed" ? "draft" : null, error: status === "failed" ? "the model answered nonsense" : null,
    result: status === "succeeded" ? { pack: "erp", datasets: 1, relationships: 0, skipped: [], dropped: [], slow: [], suggested_questions: ["Orders per month?"] } : null,
    started_at: "2026-11-14T08:00:00Z", finished_at: null,
  });

  function fakeSources(overrides: Record<string, unknown> = {}) {
    return {
      list: vi.fn(async () => []),
      test: vi.fn(async () => ({ tables: [TABLE] })),
      create: vi.fn(async () => CREATED),
      changeTables: vi.fn(async () => [{ ...TABLE, selected: true }]),
      sync: vi.fn(async () => ({ id: 1, status: "running" })),
      syncs: vi.fn(async () => [{ id: 1, status: "succeeded", results: [{ table: "orders", mode: "copy", rows: 1200 }] }]),
      instantEstimate: vi.fn(async () => ({ prompt_tokens: 12000, datasets: 1, model_missing: null })),
      instantStart: vi.fn(async () => ({ job: JOB("succeeded", Object.fromEntries(["marts", "profile", "files", "draft", "approve", "compile", "activate"].map((id) => [id, "done"]))) })),
      instantJob: vi.fn(),
      upload: vi.fn(async (file: File) => ({
        id: "u1", file_name: file.name, format: "csv", size_bytes: 2400,
        columns: [{ name: "ticket_no", type: "UInt64" }, { name: "note", type: "Nullable(String)" }], sample: [["1", "a"], ["2", null]],
      })),
      loadFile: vi.fn(async () => ({ ...CREATED, id: "sales", kind: "file" })),
      ...overrides,
    } as unknown as FitcherApi["sources"];
  }

  async function connectDatabase() {
    await userEvent.click(await screen.findByRole("radio", { name: /Connect a database/ }));
    await userEvent.type(screen.getByLabelText("Host"), "db");
    await userEvent.type(screen.getByLabelText("Database"), "erp");
    await userEvent.type(screen.getByLabelText("User"), "reader");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Check the connection" }));
  }

  it("offers a file first, loads it with the checked column types and can be left for later", async () => {
    const setup = fakeSetup(DATA_PENDING);
    const sources = fakeSources();
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={setup} {...exits()} />);

    expect(await screen.findByRole("heading", { name: "Connect your data" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load the file" }).hasAttribute("disabled")).toBe(true);
    await userEvent.upload(screen.getByLabelText("Choose a file"), new File(["ticket_no,note"], "Sales 2025.csv", { type: "text/csv" }));
    expect(await screen.findByText("Sales 2025.csv")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /See the column types \(2\)/ }));
    expect((screen.getByLabelText("Source name") as HTMLInputElement).value).toBe("sales_2025");
    expect((screen.getByLabelText("Type of ticket_no") as HTMLSelectElement).value).toBe("UInt64");
    expect((screen.getByLabelText("note can be empty") as HTMLInputElement).checked).toBe(true);
    await userEvent.selectOptions(screen.getByLabelText("Type of ticket_no"), "Int64");
    await userEvent.click(screen.getByLabelText("note can be empty"));
    await userEvent.click(screen.getByRole("button", { name: "Load the file" }));

    expect(sources.loadFile).toHaveBeenCalledWith("u1", { name: "sales_2025", columns: [{ name: "ticket_no", type: "Int64" }, { name: "note", type: "String" }] });
    expect(await screen.findByRole("heading", { name: "Choose tables" })).toBeTruthy();
  });

  it("checks a database without saving it, then saves it on Choose tables", async () => {
    const sources = fakeSources();
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} {...exits()} />);

    await connectDatabase();
    expect(await screen.findByText("Connected. 1 table found.")).toBeTruthy();
    expect(sources.create).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Choose tables" }));
    expect(sources.create).toHaveBeenCalledWith(expect.objectContaining({ name: "erp", host: "db", database: "erp", user: "reader" }));
    expect(await screen.findByRole("checkbox", { name: "orders" })).toBeTruthy();
  });

  it("says a refused connection in one fixed line under the form", async () => {
    const { SourceError } = await import("@/lib/api/http/sources");
    const sources = fakeSources({ test: vi.fn(async () => { throw new SourceError("refused", 422, "authentication"); }) });
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} {...exits()} />);

    await connectDatabase();
    expect((await screen.findByRole("alert")).textContent).toContain("The user or password was refused.");
    expect(screen.getByLabelText("Host").getAttribute("aria-invalid")).toBe("true");
  });

  it("keeps the proposed mode of each chosen table, prepares them, and builds the pack after the paid call is shown", async () => {
    const setup = fakeSetup(DATA_PENDING);
    const sources = fakeSources();
    const ways = exits();
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={setup} {...ways} />);

    await connectDatabase();
    await userEvent.click(await screen.findByRole("button", { name: "Choose tables" }));
    expect(((await screen.findByRole("checkbox", { name: "orders" })) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("tooltip", { hidden: true }).textContent).toBe("Proposed Copy: above 1 million rows.");
    await userEvent.click(screen.getByRole("button", { name: "Use 1 table" }));

    expect(sources.changeTables).toHaveBeenCalledWith("erp", {
      tables: [{ name: "orders", selected: true, mode: "copy", interval_seconds: 86_400, cursor_column: null }],
    });
    expect(sources.sync).toHaveBeenCalledWith("erp");
    expect(await screen.findByRole("heading", { name: "Build the pack from 1 table" })).toBeTruthy();
    expect(await screen.findByText(/one call of about 12,000 tokens/)).toBeTruthy();
    expect(screen.getByText("Copied · 1,200 rows")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Build the pack" }));

    expect(sources.instantStart).toHaveBeenCalledWith({ source_id: "erp", tables: ["orders"], confirm_billable: true });
    expect(await screen.findByRole("heading", { name: "The pack is ready" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Orders per month?" }));
    await waitFor(() => expect(ways.onOpenChat).toHaveBeenCalledWith("Orders per month?"));
    expect(setup.complete).toHaveBeenCalled();
  });

  it("shows the build as five lines and offers a retry when it fails", async () => {
    const failed = JOB("failed", { marts: "done", profile: "done", files: "done", draft: "failed" });
    const sources = fakeSources({ instantStart: vi.fn(async () => ({ job: failed })) });
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} {...exits()} />);

    await connectDatabase();
    await userEvent.click(await screen.findByRole("button", { name: "Choose tables" }));
    await userEvent.click(await screen.findByRole("button", { name: "Use 1 table" }));
    await userEvent.click(await screen.findByRole("button", { name: "Build the pack" }));

    const progress = await screen.findByRole("list", { name: "Pack build progress" });
    expect(within(progress).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("alert").textContent).toContain("Write descriptions and metrics failed: the model answered nonsense.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(sources.instantStart).toHaveBeenCalledTimes(2);
  });

  it("counts the items the compile has indexed with a bar and the time the build has run", async () => {
    const running = JOB("running", { marts: "done", profile: "done", files: "done", draft: "done", approve: "done", compile: "running" });
    running.steps = running.steps.map((step) => (step.id === "compile" ? { ...step, phase: "index" as const, done: 1500, total: 6000 } : step));
    const sources = fakeSources({ instantStart: vi.fn(async () => ({ job: running })), instantJob: vi.fn(async () => ({ job: running })) });
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} {...exits()} />);

    await connectDatabase();
    await userEvent.click(await screen.findByRole("button", { name: "Choose tables" }));
    await userEvent.click(await screen.findByRole("button", { name: "Use 1 table" }));
    await userEvent.click(await screen.findByRole("button", { name: "Build the pack" }));

    const progress = await screen.findByRole("list", { name: "Pack build progress" });
    expect(within(progress).getByText("1,500 of 6,000 items indexed")).toBeTruthy();
    const bar = within(progress).getByRole("progressbar") as HTMLProgressElement;
    expect(bar.max).toBe(6000);
    expect(bar.value).toBe(1500);
    expect(screen.getByText(/^Running for \d+:\d\d\./)).toBeTruthy();
  });

  it("says a model is needed instead of offering the paid call", async () => {
    const sources = fakeSources({ instantEstimate: vi.fn(async () => ({ prompt_tokens: 0, datasets: 1, model_missing: "no provider yet" })) });
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} {...exits()} />);

    await connectDatabase();
    await userEvent.click(await screen.findByRole("button", { name: "Choose tables" }));
    await userEvent.click(await screen.findByRole("button", { name: "Use 1 table" }));

    expect(await screen.findByText(/A model is needed before the pack can be built: no provider yet/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Build the pack" }).hasAttribute("disabled")).toBe(true);
  });

  it("goes back to the answered Model step and returns without changing its answer", async () => {
    const setup = fakeSetup(DATA_PENDING);
    wrap(<SetupScreen sources={fakeSources()} models={fakeModels()} setup={setup} {...exits()} />);
    await screen.findByRole("heading", { name: "Connect your data" });

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Choose the model that answers questions")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Later" }));

    expect(await screen.findByRole("heading", { name: "Connect your data" })).toBeTruthy();
    expect(setup.skip).not.toHaveBeenCalled();
  });

  it("can be left for later", async () => {
    const setup = fakeSetup(DATA_PENDING);
    wrap(<SetupScreen sources={fakeSources()} models={fakeModels()} setup={setup} {...exits()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Later" }));
    expect(setup.skip).toHaveBeenCalledWith("data");
  });
});
