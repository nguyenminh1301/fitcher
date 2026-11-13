import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { ModelsSection } from "@/components/console/sections/ModelsSection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import type { ClassifierStatus, ModelTiersView, ProviderView } from "@/lib/contracts";
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
  embedding: { backend: "local", provider_id: null, model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", dimensions: 384, needs_reindex: false },
};
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

  it("does not offer to remove a provider in use and asks before removing another", async () => {
    show();
    const openai = await screen.findByRole("listitem", { name: "OpenAI" });
    expect((within(openai).getByRole("button", { name: "Remove" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(within(screen.getByRole("listitem", { name: "Gemini" })).getByRole("button", { name: "Remove" }));
    expect(api.models.removeProvider).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Remove" })));

    await waitFor(() => expect(api.models.removeProvider).toHaveBeenCalledWith("gemini"));
  });

  it("shows each tier's model with its eval result, which never blocks a change", async () => {
    show();
    const fast = await screen.findByRole("region", { name: "fast" });
    const sqlGen = screen.getByRole("region", { name: "sql-gen" });

    expect(within(fast).getByText("Not evaluated")).toBeTruthy();
    expect(within(sqlGen).getByText("Passed the pack eval")).toBeTruthy();
    fireEvent.change(within(fast).getByLabelText("Model"), { target: { value: "gpt-5.5" } });
    await act(async () => fireEvent.click(within(fast).getByRole("button", { name: "Use this model" })));

    await waitFor(() => expect(api.models.setTier).toHaveBeenCalledWith("fast", { provider_id: "openai", model: "gpt-5.5" }));
  });

  it("asks to confirm the reindex before changing the embedding", async () => {
    show();
    const embedding = await screen.findByRole("region", { name: "Embedding" });
    expect(within(embedding).getByText(/Runs inside fitcher/)).toBeTruthy();

    fireEvent.change(within(embedding).getByLabelText("Embedding model"), {
      target: { value: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2" },
    });
    fireEvent.click(within(embedding).getByRole("button", { name: "Change the embedding model" }));
    expect(api.models.setEmbedding).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Change the embedding model" })));

    await waitFor(() => expect(api.models.setEmbedding).toHaveBeenCalledWith({
      backend: "local", model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", confirm_reindex: true,
    }));
  });

  it("says how to fetch the classifier before it can be turned on", async () => {
    show();
    const classifier = await screen.findByRole("region", { name: "Prompt-injection classifier" });

    expect(within(classifier).getByText(/docker compose run --rm guard-model/)).toBeTruthy();
    expect((within(classifier).getByRole("button", { name: "Turn on" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
