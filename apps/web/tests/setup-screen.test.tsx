import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SetupGate } from "@/components/setup/SetupGate";
import { SetupScreen } from "@/components/setup/SetupScreen";
import type { FitcherApi } from "@/lib/api/client";
import type { ModelTiersView, ProviderView, SetupStatus } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

afterEach(cleanup);

const NEW: SetupStatus = { mode: null, steps: [{ id: "mode", state: "pending" }], complete: false };

function fakeSetup(initial: SetupStatus = NEW) {
  let status = initial;
  const setup: FitcherApi["setup"] = {
    status: vi.fn(async () => status),
    setMode: vi.fn(async (mode) => (status = { mode, steps: [{ id: "mode", state: "done" }], complete: false })),
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

function wrap(node: React.ReactNode) {
  return render(<ThemeProvider><I18nProvider initial="en">{node}</I18nProvider></ThemeProvider>);
}

describe("setup screen", () => {
  it("lists the steps with the current one open", async () => {
    wrap(<SetupScreen models={fakeModels()} setup={fakeSetup()} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps.textContent).toContain("Who uses this instance");
    expect((screen.getByRole("radio", { name: /One person/ }) as HTMLInputElement).checked).toBe(true);
  });

  it("stores the chosen mode, then offers to finish", async () => {
    const setup = fakeSetup();
    wrap(<SetupScreen models={fakeModels()} setup={setup} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    await userEvent.click(await screen.findByRole("radio", { name: /A team/ }));
    await userEvent.type(screen.getByLabelText("Your e-mail"), "ana@example.com");
    await userEvent.type(screen.getByLabelText("Your name"), "Ana");
    await userEvent.type(screen.getByLabelText("Your password"), "correct horse");
    await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(setup.setMode).toHaveBeenCalledWith("team", { email: "ana@example.com", display_name: "Ana", password: "correct horse" });
    await userEvent.click(await screen.findByRole("button", { name: "Finish setup" }));
    expect(setup.complete).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Open the chat" })).toBeTruthy();
  });

  it("asks for the first admin only when the instance is not in team mode yet", async () => {
    wrap(<SetupScreen models={fakeModels()} setup={fakeSetup()} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    await screen.findByRole("radio", { name: /One person/ });
    expect(screen.queryByLabelText("Your e-mail")).toBeNull();
    cleanup();

    const stored: SetupStatus = { mode: "team", steps: [{ id: "mode", state: "pending" }], complete: false };
    const setup = fakeSetup(stored);
    wrap(<SetupScreen models={fakeModels()} setup={setup} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    await screen.findByRole("radio", { name: /A team/ });
    expect(screen.queryByLabelText("Your e-mail")).toBeNull();
  });

  it("shows the stored mode again after a reload", async () => {
    const stored: SetupStatus = { mode: "team", steps: [{ id: "mode", state: "pending" }], complete: false };
    wrap(<SetupScreen models={fakeModels()} setup={fakeSetup(stored)} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    expect(((await screen.findByRole("radio", { name: /A team/ })) as HTMLInputElement).checked).toBe(true);
  });

  it("does not let a user who is not an admin answer", async () => {
    wrap(<SetupScreen models={fakeModels()} setup={fakeSetup()} isAdmin={false} onSignedOut={() => {}} onOpenChat={() => {}} />);
    expect(await screen.findByText("Only an admin can set up this instance.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save and continue" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("signs out when the api no longer knows the session", async () => {
    const setup = fakeSetup();
    setup.status = vi.fn(async () => { throw new Error("The api answered 401: signed_out"); });
    const onSignedOut = vi.fn();
    wrap(<SetupScreen models={fakeModels()} setup={setup} isAdmin onSignedOut={onSignedOut} onOpenChat={() => {}} />);
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
  });
});

describe("setup models step", () => {
  const MODELS_PENDING: SetupStatus = {
    mode: "individual", steps: [{ id: "mode", state: "done" }, { id: "models", state: "pending" }], complete: false,
  };

  it("adds a provider with its key, tests it as a paid call and shows the proposed models", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    const models = fakeModels();
    wrap(<SetupScreen setup={setup} models={models} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);

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

  it("asks a model server for its base URL with the host hint", async () => {
    const models = fakeModels();
    wrap(<SetupScreen setup={fakeSetup(MODELS_PENDING)} models={models} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);

    await userEvent.selectOptions(await screen.findByLabelText("Provider"), "ollama");

    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(screen.getByText(/host\.docker\.internal:<port>/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Base URL"), "http://host.docker.internal:11434");
    await userEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(models.addProvider).toHaveBeenCalledWith({ kind: "ollama", base_url: "http://host.docker.internal:11434" });
  });

  it("can be skipped", async () => {
    const setup = fakeSetup(MODELS_PENDING);
    wrap(<SetupScreen setup={setup} models={fakeModels()} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);

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
    const done: SetupStatus = { mode: "individual", steps: [{ id: "mode", state: "done" }], complete: true };
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
