import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SetupGate } from "@/components/setup/SetupGate";
import { SetupScreen } from "@/components/setup/SetupScreen";
import type { FitcherApi } from "@/lib/api/client";
import type { SetupStatus } from "@/lib/contracts";
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

function wrap(node: React.ReactNode) {
  return render(<ThemeProvider><I18nProvider initial="en">{node}</I18nProvider></ThemeProvider>);
}

describe("setup screen", () => {
  it("lists the steps with the current one open", async () => {
    wrap(<SetupScreen setup={fakeSetup()} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps.textContent).toContain("Who uses this instance");
    expect((screen.getByRole("radio", { name: /One person/ }) as HTMLInputElement).checked).toBe(true);
  });

  it("stores the chosen mode, then offers to finish", async () => {
    const setup = fakeSetup();
    wrap(<SetupScreen setup={setup} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    await userEvent.click(await screen.findByRole("radio", { name: /A team/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(setup.setMode).toHaveBeenCalledWith("team");
    await userEvent.click(await screen.findByRole("button", { name: "Finish setup" }));
    expect(setup.complete).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: "Open the chat" })).toBeTruthy();
  });

  it("shows the stored mode again after a reload", async () => {
    const stored: SetupStatus = { mode: "team", steps: [{ id: "mode", state: "pending" }], complete: false };
    wrap(<SetupScreen setup={fakeSetup(stored)} isAdmin onSignedOut={() => {}} onOpenChat={() => {}} />);
    expect(((await screen.findByRole("radio", { name: /A team/ })) as HTMLInputElement).checked).toBe(true);
  });

  it("does not let a user who is not an admin answer", async () => {
    wrap(<SetupScreen setup={fakeSetup()} isAdmin={false} onSignedOut={() => {}} onOpenChat={() => {}} />);
    expect(await screen.findByText("Only an admin can set up this instance.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save and continue" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("signs out when the api no longer knows the session", async () => {
    const setup = fakeSetup();
    setup.status = vi.fn(async () => { throw new Error("The api answered 401: signed_out"); });
    const onSignedOut = vi.fn();
    wrap(<SetupScreen setup={setup} isAdmin onSignedOut={onSignedOut} onOpenChat={() => {}} />);
    await waitFor(() => expect(onSignedOut).toHaveBeenCalled());
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
