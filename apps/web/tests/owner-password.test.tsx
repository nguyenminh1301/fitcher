import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OwnerSignIn } from "@/components/chat/OwnerSignIn";
import type { FitcherApi } from "@/lib/api/client";
import { createHttpOwner, OwnerSignInError } from "@/lib/api/http/owner";
import type { OwnerStatus } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

afterEach(cleanup);

function fakeOwner(status: OwnerStatus, signIn: FitcherApi["owner"]["signIn"] = vi.fn(async () => undefined)): FitcherApi["owner"] {
  return {
    status: vi.fn(async () => status), signIn, signOut: vi.fn(async () => undefined),
    setPassword: vi.fn(async () => undefined), removePassword: vi.fn(async () => undefined),
  };
}

function wrap(node: React.ReactNode) {
  return render(<ThemeProvider><I18nProvider initial="en">{node}</I18nProvider></ThemeProvider>);
}

describe("owner sign-in page", () => {
  it("opens the app at once when no password is set", async () => {
    const onSignedIn = vi.fn();
    wrap(<OwnerSignIn owner={fakeOwner({ password_set: false, signed_in: false, exposed: false })} onSignedIn={onSignedIn} />);

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
  });

  it("signs in with the password and opens the app", async () => {
    const owner = fakeOwner({ password_set: true, signed_in: false, exposed: false });
    const onSignedIn = vi.fn();
    wrap(<OwnerSignIn owner={owner} onSignedIn={onSignedIn} />);

    await userEvent.type(await screen.findByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(owner.signIn).toHaveBeenCalledWith("correct horse battery");
    expect(onSignedIn).toHaveBeenCalled();
  });

  it.each([["wrong", "The password is not right."], ["throttled", "Too many wrong passwords. Wait a few minutes and try again."]] as const)(
    "says why a sign-in was refused (%s)", async (reason, text) => {
      const owner = fakeOwner({ password_set: true, signed_in: false, exposed: false }, vi.fn(async () => { throw new OwnerSignInError(reason); }));
      wrap(<OwnerSignIn owner={owner} onSignedIn={vi.fn()} />);

      await userEvent.type(await screen.findByLabelText("Password"), "nope nope nope");
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

      expect(await screen.findByText(text)).toBeTruthy();
    });
});

describe("http owner client", () => {
  function fetcher(status: number, body: unknown = {}) {
    return vi.fn(async (_url: string, _init?: RequestInit) => Response.json(body, { status }));
  }

  it("reads the status and sends the password changes as JSON", async () => {
    const fetch = fetcher(200, { password_set: true, signed_in: true, exposed: false });
    const owner = createHttpOwner(fetch as unknown as typeof globalThis.fetch);

    expect(await owner.status()).toEqual({ password_set: true, signed_in: true, exposed: false });
    await owner.setPassword("new long password", "old long password");
    await owner.removePassword("new long password");

    expect(fetch.mock.calls.map(([url, init]) => [url, init?.method ?? "GET", init?.body ? JSON.parse(init.body as string) : null])).toEqual([
      ["/api/owner/status", "GET", null],
      ["/api/owner/password", "PUT", { new_password: "new long password", current_password: "old long password" }],
      ["/api/owner/password", "DELETE", { current_password: "new long password" }],
    ]);
  });

  it.each([[401, "wrong"], [429, "throttled"], [500, "unavailable"]] as const)("tells a refused sign-in (%s) apart", async (status, reason) => {
    const owner = createHttpOwner(fetcher(status) as unknown as typeof globalThis.fetch);

    await expect(owner.signIn("whatever password")).rejects.toMatchObject({ reason });
  });
});
