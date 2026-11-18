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
    addProvider: vi.fn(async () => OPENAI),
    testProvider: vi.fn(async () => ({
      provider_id: "openai", models: ["gpt-5.4", "gpt-5.4-mini"], model: "gpt-5.4-mini", structured_output: true, paid: true, error: null,
    })),
    tiers: vi.fn(async () => PROPOSED),
  } as unknown as FitcherApi["models"];
}

const noSources = {} as FitcherApi["sources"];

function wrap(node: React.ReactNode) {
  return render(<ThemeProvider><I18nProvider initial="en">{node}</I18nProvider></ThemeProvider>);
}

describe("setup screen", () => {
  it("shows a bar per step, Model, Data and Start, with the current one marked", async () => {
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={fakeSetup()} isAdmin onOpenChat={() => {}} />);
    const steps = await screen.findByRole("list", { name: "Setup progress" });
    expect(within(steps).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Step 1: Model", "Step 2: Data", "Step 3: Start"]);
    expect(within(steps).getAllByRole("listitem")[0].getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("Step 1 of 3")).toBeTruthy();
  });

  it("offers to finish once every step is answered", async () => {
    const setup = fakeSetup(ANSWERED);
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Finish setup" }));
    expect(setup.complete).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Open the chat" })).toBeTruthy();
  });

  it("opens an answered step again from its bar", async () => {
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={fakeSetup(ANSWERED)} isAdmin onOpenChat={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Open the Model step again" }));
    expect(await screen.findByText("Choose the model that answers questions")).toBeTruthy();
  });

  it("does not let the sample-data demo answer", async () => {
    wrap(<SetupScreen sources={noSources} models={fakeModels()} setup={fakeSetup()} isAdmin={false} onOpenChat={() => {}} />);
    expect(await screen.findByText("Only an admin can set up this instance.")).toBeTruthy();
  });
});

describe("setup models step", () => {
  const MODELS_PENDING: SetupStatus = {
    steps: [{ id: "models", state: "pending" }], complete: false,
  };

  it("checks a key in one go, says the check is billed, and shows the model chosen for each task", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={setup} models={models} isAdmin onOpenChat={() => {}} />);

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
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.type(await screen.findByLabelText("API key"), "sk-wrong");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));

    expect((await screen.findByRole("alert")).textContent).toBe("The check failed: The key was refused.");
    expect(models.removeProvider).toHaveBeenCalledWith("openai");
    expect(screen.getByLabelText("API key").getAttribute("aria-invalid")).toBe("true");
  });

  it("removes the provider and goes back to the list when the provider is changed", async () => {
    const models = { ...fakeModels(), removeProvider: vi.fn(async () => undefined) } as unknown as FitcherApi["models"];
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.type(await screen.findByLabelText("API key"), "sk-test");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));
    await userEvent.click(await screen.findByRole("button", { name: "Change provider" }));

    expect(models.removeProvider).toHaveBeenCalledWith("openai");
    expect(await screen.findByRole("radiogroup", { name: "Provider" })).toBeTruthy();
  });

  it("suggests a model server's usual address with the Docker hint, takes no key and says nothing is billed", async () => {
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

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

  it("lists more providers by group, and adds a service from its preset with no address to type", async () => {
    const models = fakeModels();
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.click(await screen.findByRole("button", { name: "More providers" }));
    expect(screen.getByRole("group", { name: "Model services" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "On this computer" })).toBeTruthy();
    await userEvent.click(screen.getByRole("radio", { name: /Groq/ }));

    expect(screen.queryByLabelText("Address")).toBeNull();
    expect(screen.getByRole("link", { name: /Get a key from Groq/ }).getAttribute("href")).toBe("https://console.groq.com/keys");
    expect(screen.queryByRole("region", { name: "How to get an OpenRouter key" })).toBeNull();
    await userEvent.type(screen.getByLabelText("API key"), "gsk-test-1234");
    await userEvent.click(screen.getByRole("button", { name: "Check the key" }));
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "Groq", api_key: "gsk-test-1234", base_url: "https://api.groq.com/openai/v1",
    });
  });

  it("walks through creating an OpenRouter key, then maps every tier to the chosen free model and checks it", async () => {
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
    wrap(<SetupScreen sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.click(await screen.findByRole("radio", { name: /OpenRouter/ }));
    expect(screen.queryByText(/bills it/)).toBeNull();
    const guide = screen.getByRole("region", { name: "How to get an OpenRouter key" });
    await userEvent.click(within(guide).getByRole("button", { name: /Copy the key/ }));
    expect(within(guide).getByRole("button", { name: /Copy the key/ }).getAttribute("aria-current")).toBe("step");
    expect(guide.textContent).toContain("Step 4 of 4");
    expect(within(guide).getByRole("button", { name: "Play the guide" })).toBeTruthy();

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
    wrap(<SetupScreen sources={noSources} setup={setup} models={fakeModels()} isAdmin onOpenChat={() => {}} />);

    await userEvent.click(await screen.findByRole("button", { name: "Later" }));

    expect(setup.skip).toHaveBeenCalledWith("models");
  });
});

describe("setup gate", () => {
  const admin = { user_id: "a", display_name: "Ada", roles: ["admin"] };
  const member = { user_id: "m", display_name: "Max", roles: ["viewer"] };
  const gateApi = (setup: FitcherApi["setup"], identity: typeof admin | null) =>
    ({ setup, auth: { current: async () => identity } }) as unknown as Pick<FitcherApi, "setup" | "auth">;

  it("sends an admin of an unfinished setup to /setup and shows nothing", async () => {
    const redirect = vi.fn();
    wrap(<SetupGate api={gateApi(fakeSetup(), admin)} redirect={redirect}>app</SetupGate>);
    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/setup"));
    expect(screen.queryByText("app")).toBeNull();
  });

  it("tells another user that the instance is being set up", async () => {
    const redirect = vi.fn();
    wrap(<SetupGate api={gateApi(fakeSetup(), member)} redirect={redirect}>app</SetupGate>);
    expect(await screen.findByText(/being set up by an admin/)).toBeTruthy();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("opens the app once setup is complete", async () => {
    const done: SetupStatus = { steps: [{ id: "models", state: "done" }], complete: true };
    wrap(<SetupGate api={gateApi(fakeSetup(done), member)} redirect={() => {}}>app</SetupGate>);
    expect(await screen.findByText("app")).toBeTruthy();
  });

  it("opens the app when the status cannot be read", async () => {
    const setup = fakeSetup();
    setup.status = vi.fn(async () => { throw new Error("down"); });
    wrap(<SetupGate api={gateApi(setup, admin)} redirect={() => {}}>app</SetupGate>);
    expect(await screen.findByText("app")).toBeTruthy();
  });
});


describe("setup data step", () => {
  const DATA_PENDING: SetupStatus = {
    steps: [{ id: "models", state: "done" }, { id: "data", state: "pending" }],
    complete: false,
  };
  const TABLE = {
    name: "orders", kind: "table" as const, rows: 10, size_bytes: 2048, columns: [{ name: "id", type: "integer", nullable: false }],
    primary_key: ["id"], foreign_keys: [], unusual_columns: [], selected: false, mode: "live" as const, proposed_mode: "live" as const,
    reason: "small", slow: false, interval_seconds: 86_400, cursor_column: null, cursor_candidates: ["id"], last_synced_at: null,
    last_rows: null, next_run_at: null,
  };
  const CREATED = {
    id: "erp", kind: "postgres" as const, host: "db", port: 5432, database: "erp", schema_name: "public", user: "reader",
    tls_mode: "prefer" as const, has_ca: false, created_at: "2026-11-14T08:00:00Z", table_count: 1, selected_count: 0, last_sync: null,
    tables: [TABLE],
  };

  function fakeSources() {
    return {
      test: vi.fn(async () => ({ tables: [TABLE] })),
      create: vi.fn(async () => CREATED),
      changeTables: vi.fn(async () => [{ ...TABLE, selected: true }]),
      sync: vi.fn(async () => ({ id: 1, status: "running" })),
    } as unknown as FitcherApi["sources"];
  }

  it("asks which data to read and can be skipped", async () => {
    const setup = fakeSetup(DATA_PENDING);
    wrap(<SetupScreen sources={fakeSources()} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);

    expect(await screen.findByText("Which data should fitcher read?")).toBeTruthy();
    expect(screen.getByLabelText("Host")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(setup.skip).toHaveBeenCalledWith("data");
  });

  it("connects a database, saves and prepares its tables and continues without a pack", async () => {
    const setup = fakeSetup(DATA_PENDING);
    const sources = fakeSources();
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);
    await screen.findByText("Which data should fitcher read?");

    await userEvent.type(screen.getByLabelText("Name"), "erp");
    await userEvent.type(screen.getByLabelText("Host"), "db");
    await userEvent.type(screen.getByLabelText("Database"), "erp");
    await userEvent.type(screen.getByLabelText("User"), "reader");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Use orders" }));
    await userEvent.click(screen.getByRole("button", { name: "Save and prepare tables" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue without a pack" }));

    expect(sources.create).toHaveBeenCalledWith(expect.objectContaining({ name: "erp", password: "pw" }));
    expect(sources.changeTables).toHaveBeenCalled();
    expect(sources.sync).toHaveBeenCalledWith("erp");
    await waitFor(() => expect(setup.status).toHaveBeenCalledTimes(2));
  });

  it("offers the instant pack as soon as the chosen tables are saved and prepared, then opens the chat", async () => {
    const setup = fakeSetup(DATA_PENDING);
    const ready = {
      id: "job1", source_id: "erp", tables: ["orders"], status: "succeeded", started_at: "2026-11-15T10:00:00Z", finished_at: null,
      failed_step: null, error: null, steps: [{ id: "marts", state: "done" }],
      result: { pack: "erp", datasets: 1, relationships: 0, skipped: [], dropped: [], slow: [], suggested_questions: ["Orders per month?"] },
    };
    const sources = {
      ...fakeSources(),
      syncs: vi.fn(async () => [{ id: 1, status: "succeeded" }]),
      instantEstimate: vi.fn(async () => ({ prompt_tokens: 1200, datasets: 1, model_missing: null })),
      instantStart: vi.fn(async () => ({ job: ready })),
    } as unknown as FitcherApi["sources"];
    const onOpenChat = vi.fn();
    wrap(<SetupScreen sources={sources} models={fakeModels()} setup={setup} isAdmin onOpenChat={onOpenChat} />);
    await screen.findByText("Which data should fitcher read?");
    await userEvent.type(screen.getByLabelText("Name"), "erp");
    await userEvent.type(screen.getByLabelText("Host"), "db");
    await userEvent.type(screen.getByLabelText("Database"), "erp");
    await userEvent.type(screen.getByLabelText("User"), "reader");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    await userEvent.click(await screen.findByRole("button", { name: "Connect" }));
    expect(((await screen.findByRole("checkbox", { name: "Use orders" })) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByRole("region", { name: "Build the pack" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save and prepare tables" }));

    await userEvent.click(await screen.findByRole("button", { name: "Build the pack" }));
    expect(sources.instantStart).toHaveBeenCalledWith({ source_id: "erp", tables: ["orders"], confirm_billable: true });
    await userEvent.click(await screen.findByRole("button", { name: "Orders per month?" }));

    await waitFor(() => expect(onOpenChat).toHaveBeenCalledWith("Orders per month?"));
    expect(setup.skip).not.toHaveBeenCalled();
    expect(setup.complete).toHaveBeenCalled();
  });

  it("goes back to the answered Models step and returns without changing its answer", async () => {
    const setup = fakeSetup(DATA_PENDING);
    wrap(<SetupScreen sources={fakeSources()} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);
    await screen.findByText("Which data should fitcher read?");

    await userEvent.click(screen.getByRole("button", { name: "Back to Model" }));

    expect(await screen.findByText("Choose the model that answers questions")).toBeTruthy();
    const steps = screen.getByRole("list", { name: "Setup progress" });
    expect(within(steps).getAllByRole("listitem")[0].getAttribute("aria-current")).toBe("step");
    await userEvent.click(screen.getByRole("button", { name: "Later" }));

    expect(await screen.findByText("Which data should fitcher read?")).toBeTruthy();
    expect(setup.skip).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Open the Model step again" }));
    expect(await screen.findByText("Choose the model that answers questions")).toBeTruthy();
  });

  it("does not let a user who is not an admin connect a source", async () => {
    wrap(<SetupScreen sources={fakeSources()} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} isAdmin={false} onOpenChat={() => {}} />);

    expect(await screen.findByText("Only an admin can set up this instance.")).toBeTruthy();
    expect(screen.queryByLabelText("Host")).toBeNull();
  });
});
