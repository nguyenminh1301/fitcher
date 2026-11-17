import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  steps: [{ id: "models", state: "pending" }, { id: "data", state: "pending" }, { id: "documents", state: "pending" }], complete: false,
};
const ANSWERED: SetupStatus = {
  steps: [{ id: "models", state: "done" }, { id: "data", state: "skipped" }, { id: "documents", state: "done" }], complete: false,
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

function fakeDocuments(kept = 0) {
  let enabled = true;
  return {
    settings: vi.fn(async () => ({ enabled, documents: kept })),
    setEnabled: vi.fn(async (next: boolean, confirm = false) => {
      if (!next && enabled && kept && !confirm) throw new Error("The api answered 409: 1 document stays stored");
      enabled = next;
      return { enabled, documents: kept };
    }),
    upload: vi.fn(async (file: File) => ({ id: "d1", name: file.name })),
  } as unknown as FitcherApi["documents"];
}

function documentProps(documents = fakeDocuments(), roles: string[] | null = null) {
  return { documents, packRoles: () => (roles ? Promise.resolve(roles) : Promise.reject(new Error("no active pack"))) };
}

const DOCUMENTS_PENDING: SetupStatus = {
  complete: false,
  steps: [{ id: "models", state: "done" }, { id: "data", state: "done" }, { id: "documents", state: "pending" }],
};

function wrap(node: React.ReactNode) {
  return render(<ThemeProvider><I18nProvider initial="en">{node}</I18nProvider></ThemeProvider>);
}

describe("setup screen", () => {
  it("lists the steps with the current one open, and no step asks who uses the instance", async () => {
    wrap(<SetupScreen {...documentProps()} sources={noSources} models={fakeModels()} setup={fakeSetup()} isAdmin onOpenChat={() => {}} />);
    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps.textContent).toContain("Models");
    expect(steps.textContent).not.toContain("Who uses this instance");
    expect(screen.queryByRole("radio", { name: /A team/ })).toBeNull();
  });

  it("offers to finish once every step is answered", async () => {
    const setup = fakeSetup(ANSWERED);
    wrap(<SetupScreen {...documentProps()} sources={noSources} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Finish setup" }));
    expect(setup.complete).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Open the chat" })).toBeTruthy();
  });

  it("does not let the sample-data demo answer", async () => {
    wrap(<SetupScreen {...documentProps()} sources={noSources} models={fakeModels()} setup={fakeSetup()} isAdmin={false} onOpenChat={() => {}} />);
    expect(await screen.findByText("Only an admin can set up this instance.")).toBeTruthy();
  });
});

describe("setup models step", () => {
  const MODELS_PENDING: SetupStatus = {
    steps: [{ id: "models", state: "pending" }], complete: false,
  };

  it("adds a provider with its key, tests it as a paid call and shows the proposed models", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    const models = fakeModels();
    wrap(<SetupScreen {...documentProps()} sources={noSources} setup={setup} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.type(await screen.findByLabelText("API key"), "sk-test-0000-7777");
    await userEvent.click(screen.getByRole("button", { name: "Add provider" }));

    expect(models.addProvider).toHaveBeenCalledWith({ kind: "openai", api_key: "sk-test-0000-7777" });
    expect(await screen.findByText("The test sends one small request to OpenAI, which bills it.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText("gpt-5.4-mini answered with structured output; 2 models listed.")).toBeTruthy();
    const proposed = screen.getByLabelText("Proposed models");
    expect(proposed.textContent).toContain("sql-gen");
    expect(proposed.textContent).toContain("gpt-5.4");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(setup.status).toHaveBeenCalledTimes(2));
  });

  it("suggests a model server's usual address with the host hint, and takes no key", async () => {
    const models = fakeModels();
    wrap(<SetupScreen {...documentProps()} sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.selectOptions(await screen.findByLabelText("Provider"), "ollama");

    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(screen.getByText(/host\.docker\.internal:<port>/)).toBeTruthy();
    const address = screen.getByLabelText("Base URL");
    expect((address as HTMLInputElement).value).toBe("http://host.docker.internal:11434");
    await userEvent.clear(address);
    await userEvent.type(address, "http://192.168.1.20:11434");
    await userEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(models.addProvider).toHaveBeenCalledWith({ kind: "ollama", base_url: "http://192.168.1.20:11434" });
  });

  it("adds an OpenAI-compatible service from its preset, with a link to its key page and no address to type", async () => {
    const models = fakeModels();
    wrap(<SetupScreen {...documentProps()} sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.selectOptions(await screen.findByLabelText("Provider"), "groq");

    expect(screen.queryByLabelText("Base URL")).toBeNull();
    expect(screen.getByRole("link", { name: /Get a key from Groq/ }).getAttribute("href")).toBe("https://console.groq.com/keys");
    expect(screen.queryByRole("region", { name: "How to get an OpenRouter key" })).toBeNull();
    await userEvent.type(screen.getByLabelText("API key"), "gsk-test-1234");
    await userEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "Groq", api_key: "gsk-test-1234", base_url: "https://api.groq.com/openai/v1",
    });
  });

  it("walks through creating an OpenRouter key, then maps every tier to the chosen free model", async () => {
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
      testProvider: vi.fn(),
    } as unknown as FitcherApi["models"];
    wrap(<SetupScreen {...documentProps()} sources={noSources} setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onOpenChat={() => {}} />);

    await userEvent.selectOptions(await screen.findByLabelText("Provider"), "openrouter");
    const guide = screen.getByRole("region", { name: "How to get an OpenRouter key" });
    expect(guide.textContent).toContain("Create a key named fitcher");
    await userEvent.click(screen.getByRole("button", { name: /Copy the key/ }));
    expect(screen.getByRole("button", { name: /Copy the key/ }).getAttribute("aria-current")).toBe("step");
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();

    await userEvent.type(screen.getByLabelText("API key"), "sk-or-v1-test");
    await userEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(models.addProvider).toHaveBeenCalledWith({
      kind: "openai_compatible", name: "OpenRouter", api_key: "sk-or-v1-test", base_url: "https://openrouter.ai/api/v1",
    });

    const chosen = await screen.findByLabelText("Model");
    expect(screen.getByText("2 of 3 models shown")).toBeTruthy();
    expect(chosen.textContent).not.toContain("openai/gpt-5.4");
    await userEvent.click(screen.getByRole("button", { name: /Free models only/ }));
    expect(screen.getByText("3 of 3 models shown")).toBeTruthy();
    await userEvent.selectOptions(chosen, "qwen/qwen3-coder:free");
    await userEvent.click(screen.getByRole("button", { name: "Use this model" }));

    await waitFor(() => expect(models.setTier).toHaveBeenCalledTimes(4));
    expect(models.setTier).toHaveBeenCalledWith("sql-gen-hard", { provider_id: OPENROUTER.id, model: "qwen/qwen3-coder:free" });
    await userEvent.click(await screen.findByRole("button", { name: "Test" }));
    expect(models.testProvider).toHaveBeenCalledWith(OPENROUTER.id, "qwen/qwen3-coder:free");
  });

  it("can be skipped", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    wrap(<SetupScreen {...documentProps()} sources={noSources} setup={setup} models={fakeModels()} isAdmin onOpenChat={() => {}} />);

    await userEvent.click(await screen.findByRole("button", { name: "Skip for now" }));

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
    wrap(<SetupScreen {...documentProps()} sources={fakeSources()} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);

    expect(await screen.findByText("Which data should fitcher read?")).toBeTruthy();
    expect(screen.getByLabelText("Host")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Skip for now" }));

    expect(setup.skip).toHaveBeenCalledWith("data");
  });

  it("connects a database, saves and prepares its tables and continues without a pack", async () => {
    const setup = fakeSetup(DATA_PENDING);
    const sources = fakeSources();
    wrap(<SetupScreen {...documentProps()} sources={sources} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);
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
    wrap(<SetupScreen {...documentProps()} sources={sources} models={fakeModels()} setup={setup} isAdmin onOpenChat={onOpenChat} />);
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

    await waitFor(() => expect(onOpenChat).toHaveBeenCalled());
    expect(setup.skip).toHaveBeenCalledWith("documents");
    expect(setup.complete).toHaveBeenCalled();
  });

  it("does not let a user who is not an admin connect a source", async () => {
    wrap(<SetupScreen {...documentProps()} sources={fakeSources()} models={fakeModels()} setup={fakeSetup(DATA_PENDING)} isAdmin={false} onOpenChat={() => {}} />);

    expect(await screen.findByText("Only an admin can set up this instance.")).toBeTruthy();
    expect(screen.queryByLabelText("Host")).toBeNull();
  });

  it("turns documents off from the Documents step, confirming when documents are kept", async () => {
    const documents = fakeDocuments(1);
    const setup = fakeSetup(DOCUMENTS_PENDING);
    wrap(<SetupScreen {...documentProps(documents)} sources={noSources} models={fakeModels()} setup={setup} isAdmin onOpenChat={() => {}} />);

    await userEvent.click(await screen.findByRole("radio", { name: "No documents" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/1 kept documents stay stored/)).toBeTruthy();
    expect(setup.status).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Turn documents off" }));
    await waitFor(() => expect(documents.setEnabled).toHaveBeenLastCalledWith(false, true));
    await waitFor(() => expect(setup.status).toHaveBeenCalledTimes(2));
  });

  it("uploads documents in place when a pack is active", async () => {
    const documents = fakeDocuments();
    wrap(<SetupScreen {...documentProps(documents, ["analyst", "sales"])} sources={noSources} models={fakeModels()} setup={fakeSetup(DOCUMENTS_PENDING)} isAdmin onOpenChat={() => {}} />);

    const file = new File(["# Returns"], "returns.md", { type: "text/markdown" });
    await screen.findByText(/Upload documents now/);
    await act(async () => fireEvent.change(document.querySelector("input[type=file]")!, { target: { files: [file] } }));

    await waitFor(() => expect(documents.upload).toHaveBeenCalledWith(file, ["analyst", "sales"]));
    expect(await screen.findByText("returns.md")).toBeTruthy();
  });

  it("points to the Documents page when no pack is active yet", async () => {
    wrap(<SetupScreen {...documentProps()} sources={noSources} models={fakeModels()} setup={fakeSetup(DOCUMENTS_PENDING)} isAdmin onOpenChat={() => {}} />);

    expect(await screen.findByText(/once your data is connected/)).toBeTruthy();
  });
});
