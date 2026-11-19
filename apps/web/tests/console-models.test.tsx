import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { ModelsSection } from "@/components/console/sections/ModelsSection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import type { CatalogEntry, ClassifierStatus, ModelTiersView, ProviderView } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

configure({ asyncUtilTimeout: 4000 });

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst"],
  identities: [{ user_id: "adm", display_name: "Ada Admin", roles: ["admin", "analyst"] }],
  conversations: [],
};

const OPENAI: ProviderView = {
  id: "openai", name: "OpenAI", kind: "openai", base_url: null, key_set: true, key_last4: "7777", hosted: true, in_use: true,
};
const GEMINI: ProviderView = { ...OPENAI, id: "gemini", name: "Gemini", kind: "gemini", key_last4: "1234", in_use: false };

const TIERS: ModelTiersView = {
  tiers: [
    { tier: "fast", provider_id: "openai", model: "gpt-5.4-mini", eval: { evaluated: false, passed: false, reason: "no eval report ran fast with openai/gpt-5.4-mini" } },
    { tier: "sql-gen", provider_id: "openai", model: "gpt-5.4", eval: { evaluated: true, passed: true, reason: "passed", report_id: "r1", report_ts: "2026-11-10T08:00:00Z" } },
  ],
  mode: "manual",
  embedding: { backend: "local", provider_id: null, model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", dimensions: 384, needs_reindex: false },
};
function entry(provider_id: string, id: string, change: Partial<CatalogEntry> = {}): CatalogEntry {
  return { id, provider_id, kind: "chat", free: "none", input_price: 1.25, output_price: 10, context: 400000,
           structured_output: true, benchmark: 50, median_latency_ms: null, ...change };
}

const CATALOG: CatalogEntry[] = [
  entry("openai", "gpt-5.5", { benchmark: 70 }),
  entry("openai", "gpt-5.4-mini", { benchmark: 40, input_price: 0.25, output_price: 2 }),
  entry("openai", "text-embedding-3-large", { kind: "embedding" }),
  entry("gemini", "gemini-flash-lite-latest", { free: "free_tier", benchmark: 35, median_latency_ms: 800, input_price: null, output_price: null }),
  entry("gemini", "gemini-3.8-flash", { free: "free_tier", benchmark: 60, input_price: null, output_price: null }),
];
const CLASSIFIER: ClassifierStatus = { enabled: false, model_present: false, version: null };

let api: MockApi;

function show() {
  window.localStorage.setItem("fitcher.demo.identity", "adm");
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{ auth: "mock", models: "http" }}>
          <ConsoleLayout section="models" navigate={vi.fn()} onChat={vi.fn()}><ModelsSection /></ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
  api = createMockApi();
  Object.assign(api.models, {
    providers: vi.fn(async () => [OPENAI, GEMINI]),
    tiers: vi.fn(async () => TIERS),
    classifier: vi.fn(async () => CLASSIFIER),
    providerModels: vi.fn(async () => ({ provider_id: "openai", models: ["gpt-5.4", "gpt-5.5"] })),
    setTier: vi.fn(async (tier: string, change: { provider_id: string; model: string }) => ({ tier, ...change, eval: null })),
    setEmbedding: vi.fn(async () => TIERS.embedding),
    setMode: vi.fn(async () => ({ ...TIERS, mode: "auto_free" })),
    catalog: vi.fn(async (id: string) => ({ provider_id: id, models: CATALOG.filter((entry) => entry.provider_id === id) })),
    removeProvider: vi.fn(async () => undefined),
    setClassifier: vi.fn(async () => CLASSIFIER),
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("models", () => {
  it("lists providers with only the end of their key and no Sample data badge", async () => {
    show();
    const providers = await screen.findByRole("region", { name: "Providers" });

    expect(within(providers).getByText(/Key ending in 7777/)).toBeTruthy();
    expect(within(providers).getByText(/Key ending in 1234/)).toBeTruthy();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("renames a provider and shows its logo", async () => {
    api.models.changeProvider = vi.fn(async () => ({ ...GEMINI, name: "Gemini work" }));
    show();
    const gemini = await screen.findByRole("group", { name: "Gemini" });
    expect(gemini.querySelector('img[src="/providers/gemini.svg"]')).toBeTruthy();

    fireEvent.click(within(gemini).getByRole("button", { name: "Rename Gemini" }));
    const name = within(gemini).getByLabelText("Name");
    fireEvent.change(name, { target: { value: "  Gemini work " } });
    await act(async () => fireEvent.click(within(gemini).getByRole("button", { name: "Save name" })));

    await waitFor(() => expect(api.models.changeProvider).toHaveBeenCalledWith("gemini", { name: "Gemini work" }));
  });

  it("removes a provider in use after asking, saying where its tasks go", async () => {
    show();
    const openai = await screen.findByRole("group", { name: "OpenAI" });

    fireEvent.click(within(openai).getByRole("button", { name: "Remove OpenAI" }));
    expect(api.models.removeProvider).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(/tasks it serves move to another provider/)).toBeTruthy();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Remove" })));

    await waitFor(() => expect(api.models.removeProvider).toHaveBeenCalledWith("openai"));
  });

  it("shows each task's chain with its evaluation and builds a new chain from a searchable, filtered picker", async () => {
    show();
    const fast = await screen.findByRole("listitem", { name: "Quick" });
    expect(within(fast).getByText("gpt-5.4-mini")).toBeTruthy();
    expect(within(fast).getByText("Not evaluated")).toBeTruthy();
    expect(screen.getByText("Passed the pack evaluation")).toBeTruthy();

    const change = within(fast).getByRole("button", { name: "Change the models of Quick" });
    await waitFor(() => expect((change as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(change);
    const dialog = await screen.findByRole("dialog", { name: "Models for Quick" });
    const list = within(dialog).getByRole("list", { name: "Models of your providers" });
    // Only chat models are listed, the best free one first and recommended.
    expect(within(list).queryByText("text-embedding-3-large")).toBeNull();
    expect(within(list).getAllByRole("listitem")[0].textContent).toContain("gemini-3.8-flash");
    expect(within(within(list).getAllByRole("listitem")[0]).getByText("Recommended")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Free" }));
    expect(within(list).queryByText("gpt-5.5")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Free" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Search models" }), { target: { value: "lite" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add gemini-flash-lite-latest" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Move gemini-flash-lite-latest up" }));
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Save order" })));

    await waitFor(() => expect(api.models.setTier).toHaveBeenCalledWith("fast", { chain: [
      { provider_id: "gemini", model: "gemini-flash-lite-latest" }, { provider_id: "openai", model: "gpt-5.4-mini" },
    ] }));
  });

  it("switches how the models are chosen", async () => {
    show();
    const mode = await screen.findByRole("radiogroup", { name: "How the models are chosen" });

    await act(async () => fireEvent.click(within(mode).getByRole("radio", { name: "Free models, automatic" })));

    await waitFor(() => expect(api.models.setMode).toHaveBeenCalledWith("auto_free"));
  });

  it("asks to confirm the reindex before changing the embedding", async () => {
    show();
    const embedding = await screen.findByRole("region", { name: "Embedding" });
    expect(within(embedding).getByText("Inside fitcher")).toBeTruthy();

    fireEvent.click(within(embedding).getByRole("button", { name: "Change the embedding model" }));
    const dialog = screen.getByRole("dialog", { name: "Change the embedding model?" });
    fireEvent.change(within(dialog).getByLabelText("Model"), { target: { value: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Change model" })));

    await waitFor(() => expect(api.models.setEmbedding).toHaveBeenCalledWith({
      backend: "local", model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", confirm_reindex: true,
    }));
  });

  it("turns the classifier on through a provider that lists a Prompt Guard model in one click", async () => {
    Object.assign(api.models, {
      providerModels: vi.fn(async (id: string) => ({ provider_id: id, models: id === "gemini"
        ? ["gemini-2.5-flash"] : ["gpt-5.4", "meta-llama/llama-prompt-guard-2-22m", "meta-llama/llama-prompt-guard-2-86m"] })),
      changeClassifier: vi.fn(async () => ({ ...CLASSIFIER, enabled: true, provider_id: "openai", model: "meta-llama/llama-prompt-guard-2-86m" })),
    });
    show();
    const classifier = await screen.findByRole("region", { name: "Prompt-injection filter" });
    const toggle = within(classifier).getByRole("switch", { name: "Prompt-injection filter" }) as HTMLButtonElement;
    await waitFor(() => expect(toggle.disabled).toBe(false));

    await act(async () => fireEvent.click(toggle));

    expect(api.models.changeClassifier).toHaveBeenCalledWith({
      enabled: true, engine: "provider", provider_id: "openai", model: "meta-llama/llama-prompt-guard-2-86m",
    });
  });

  it("offers Groq or the download when no provider hosts the classifier, and downloads with progress", async () => {
    Object.assign(api.models, {
      startClassifierDownload: vi.fn(async () => ({ state: "downloading", bytes_done: 10_000_000, bytes_total: 300_000_000 })),
      classifierDownload: vi.fn(async () => ({ state: "downloading", bytes_done: 20_000_000, bytes_total: 300_000_000 })),
    });
    show();
    const classifier = await screen.findByRole("region", { name: "Prompt-injection filter" });

    expect(await within(classifier).findByText(/Add Groq \(free\)/)).toBeTruthy();
    expect((within(classifier).getByRole("switch", { name: "Prompt-injection filter" }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(classifier).getByText(/rules check every question, even when the filter is off/)).toBeTruthy();

    fireEvent.click(within(classifier).getByRole("radio", { name: "On this computer" }));
    await act(async () => fireEvent.click(within(classifier).getByRole("button", { name: /Download the model/ })));

    expect(api.models.startClassifierDownload).toHaveBeenCalled();
    expect(within(classifier).getByRole("progressbar", { name: "Download progress" })).toBeTruthy();
    expect(within(classifier).getByText("10 MB / 300 MB")).toBeTruthy();
  });

  it("adds a provider from the cards, checks it, and removes it again when the check fails", async () => {
    Object.assign(api.models, {
      addProvider: vi.fn(async () => GEMINI),
      testProvider: vi.fn(async () => ({ provider_id: "gemini", models: [], model: null, structured_output: false, paid: true, error: "The key was refused." })),
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Add a provider" }));
    const dialog = screen.getByRole("dialog", { name: "Add a provider" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Gemini/ }));
    fireEvent.change(within(dialog).getByLabelText("API key"), { target: { value: "AIza-test" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Check and add" })));

    expect(api.models.addProvider).toHaveBeenCalledWith({ kind: "gemini", api_key: "AIza-test" });
    expect((await within(dialog).findByRole("alert")).textContent).toContain("The key was refused.");
    expect(api.models.removeProvider).toHaveBeenCalledWith("gemini");
  });
});
