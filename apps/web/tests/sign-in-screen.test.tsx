import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignInScreen } from "@/components/chat/SignInScreen";
import type { FitcherApi } from "@/lib/api/client";
import { SignInError } from "@/lib/api/provisional";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

afterEach(cleanup);

function fakeAuth(overrides: Partial<FitcherApi["auth"]> = {}): FitcherApi["auth"] {
  return {
    identities: vi.fn(async () => []),
    current: vi.fn(async () => null),
    switchTo: vi.fn(),
    pack: vi.fn(async () => ({ name: "shop", display_name: "Shop", roles: [] })),
    signIn: vi.fn(async () => undefined),
    oidcEnabled: vi.fn(async () => false),
    signOut: vi.fn(async () => "/sign-in"),
    ...overrides,
  };
}

function show(auth: FitcherApi["auth"], failed = false) {
  const onSignedIn = vi.fn();
  render(<ThemeProvider><I18nProvider><SignInScreen auth={auth} failed={failed} onSignedIn={onSignedIn} /></I18nProvider></ThemeProvider>);
  return onSignedIn;
}

async function submit(email: string, password: string) {
  await userEvent.type(screen.getByLabelText("E-mail"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("sign-in screen", () => {
  it("signs in with an e-mail and password and opens the app", async () => {
    const auth = fakeAuth();
    const onSignedIn = show(auth);

    await submit("ana@example.com", "correct horse");

    expect(auth.signIn).toHaveBeenCalledWith("ana@example.com", "correct horse");
    expect(onSignedIn).toHaveBeenCalledTimes(1);
  });

  it("says when the e-mail or password is wrong, without saying which", async () => {
    const onSignedIn = show(fakeAuth({ signIn: vi.fn(async () => { throw new SignInError("invalid"); }) }));

    await submit("ana@example.com", "wrong");

    expect(await screen.findByText("The e-mail or password is not right.")).toBeTruthy();
    expect(onSignedIn).not.toHaveBeenCalled();
  });

  it("asks to wait after too many failed sign-ins", async () => {
    show(fakeAuth({ signIn: vi.fn(async () => { throw new SignInError("throttled"); }) }));

    await submit("ana@example.com", "wrong");

    expect(await screen.findByText("Too many failed sign-ins. Wait a few minutes and try again.")).toBeTruthy();
  });

  it("offers the company provider only when one is set up", async () => {
    show(fakeAuth({ oidcEnabled: vi.fn(async () => true) }));

    expect(await screen.findByRole("button", { name: "Continue with company account" })).toBeTruthy();
    cleanup();

    show(fakeAuth());
    await screen.findByRole("button", { name: "Sign in" });
    expect(screen.queryByRole("button", { name: "Continue with company account" })).toBeNull();
  });

  it("says when a sign-in through the provider failed", async () => {
    show(fakeAuth(), true);

    expect(await screen.findByText("Sign-in did not complete. Try again.")).toBeTruthy();
  });

  it("opens the app at once when no sign-in is needed", async () => {
    const onSignedIn = show(fakeAuth({ current: vi.fn(async () => ({ user_id: "owner", display_name: "Owner", roles: [], mode: "individual" as const })) }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
  });
});
