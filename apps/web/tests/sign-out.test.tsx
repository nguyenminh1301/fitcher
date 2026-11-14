import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSignOut } from "@/lib/chat/useSignOut";
import { I18nProvider } from "@/lib/i18n/react";

const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider initial="en">{children}</I18nProvider>;

afterEach(() => vi.restoreAllMocks());

describe("sign-out", () => {
  it("opens the address the api gives after signing out", async () => {
    const open = vi.fn();
    const { result } = renderHook(() => useSignOut(async () => "/sign-in", open), { wrapper });

    await act(async () => result.current());

    expect(open).toHaveBeenCalledWith("/sign-in");
  });

  it("tells the user when sign-out did not complete, so they can try again", async () => {
    const open = vi.fn();
    const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const { result } = renderHook(() => useSignOut(async () => { throw new Error("sign-out answered 502"); }, open), { wrapper });

    await act(async () => result.current());

    expect(open).not.toHaveBeenCalled();
    expect(alert).toHaveBeenCalledWith("Sign-out did not complete, so you may still be signed in. Try again.");
  });
});
