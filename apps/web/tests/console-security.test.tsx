import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { SecuritySection } from "@/components/console/sections/SecuritySection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import type { OwnerStatus } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

const CONSOLE: Partial<ConsoleFile> = { pack: { name: "shop", display_name: "Shop" }, identities: [], conversations: [] };

let api: MockApi;

function show(status: OwnerStatus) {
  Object.assign(api.owner, {
    status: vi.fn(async () => status),
    setPassword: vi.fn(async () => undefined),
    removePassword: vi.fn(async () => undefined),
  });
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null}>
          <ConsoleLayout section="security" navigate={vi.fn()} onChat={vi.fn()}><SecuritySection /></ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
  api = createMockApi();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("security", () => {
  it("sets a first password only when both entries match, and says a forgotten one cannot be recovered", async () => {
    show({ password_set: false, signed_in: false, exposed: false });
    const form = await screen.findByRole("form", { name: "Set an owner password" });

    fireEvent.change(within(form).getByLabelText("New password"), { target: { value: "long enough" } });
    fireEvent.change(within(form).getByLabelText("Repeat it"), { target: { value: "long enougX" } });
    expect(within(form).getByRole("alert").textContent).toContain("The two passwords are not the same.");
    expect((within(form).getByRole("button", { name: "Set password" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(within(form).getByLabelText("Repeat it"), { target: { value: "long enough" } });
    await act(async () => fireEvent.click(within(form).getByRole("button", { name: "Set password" })));
    expect(api.owner.setPassword).toHaveBeenCalledWith("long enough", undefined);
    expect(screen.getByText(/no way to recover it/)).toBeTruthy();
  });

  it("changes the password with the current one, and keeps it while fitcher is open to other machines", async () => {
    show({ password_set: true, signed_in: true, exposed: true });
    const form = await screen.findByRole("form", { name: "Change the password" });
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.change(within(form).getByLabelText("Current password"), { target: { value: "old password" } });
    const remove = screen.getByRole("button", { name: "Remove password" }) as HTMLButtonElement;
    expect(remove.disabled).toBe(true);
    expect(screen.getByText("It cannot be removed while fitcher is open to other machines.")).toBeTruthy();

    fireEvent.change(within(form).getByLabelText("New password"), { target: { value: "new password" } });
    fireEvent.change(within(form).getByLabelText("Repeat it"), { target: { value: "new password" } });
    await act(async () => fireEvent.click(within(form).getByRole("button", { name: "Change password" })));
    await waitFor(() => expect(api.owner.setPassword).toHaveBeenCalledWith("new password", "old password"));
    expect(await screen.findByText("Changed. Other browsers must sign in again.")).toBeTruthy();
  });

  it("warns when fitcher is open to other machines without a password", async () => {
    show({ password_set: false, signed_in: false, exposed: true });
    expect((await screen.findByRole("alert")).textContent).toContain("Set an owner password on this computer");
  });
});
