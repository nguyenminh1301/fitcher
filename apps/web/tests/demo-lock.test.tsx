import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProviderPicker } from "@/components/models/ProviderPicker";
import { DemoLocked } from "@/components/ui/DemoLock";
import { createMockApi } from "@/lib/api/mock";
import { sampleUrl } from "@/lib/api/mock/load";
import { I18nProvider } from "@/lib/i18n/react";

const NOTICE = "Don't put your api key on a random website 🙂";

afterEach(() => cleanup());

function picker(demo: boolean) {
  render(
    <I18nProvider initial="en">
      <ProviderPicker presetId="openai" onPreset={vi.fn()} apiKey="sk-typed" onApiKey={vi.fn()} address="" onAddress={vi.fn()} demo={demo} />
    </I18nProvider>,
  );
  return screen.getByLabelText(/API key/i) as HTMLInputElement;
}

describe("public demo lock", () => {
  it("locks and empties the key field in the demo and says why", () => {
    const key = picker(true);

    expect(key.disabled).toBe(true);
    expect(key.value).toBe("");
    expect(screen.getByText(NOTICE)).toBeTruthy();
    expect(key.getAttribute("aria-describedby")).toContain(screen.getByText(NOTICE).closest("[id]")?.id ?? "missing");
  });

  it("keeps the key field editable in the installed app", () => {
    const key = picker(false);

    expect(key.disabled).toBe(false);
    expect(key.value).toBe("sk-typed");
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it("disables every control of a locked form in the demo only", () => {
    const form = (demo: boolean) => (
      <I18nProvider initial="en">
        <DemoLocked demo={demo}><input aria-label="password" /><button type="submit">Save</button></DemoLocked>
      </I18nProvider>
    );
    const { rerender } = render(form(true));

    expect((screen.getByLabelText("password") as HTMLInputElement).matches(":disabled")).toBe(true);
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).matches(":disabled")).toBe(true);
    expect(screen.getByText(/Install fitcher/)).toBeTruthy();

    rerender(form(false));
    expect((screen.getByLabelText("password") as HTMLInputElement).matches(":disabled")).toBe(false);
    expect(screen.queryByText(/Install fitcher/)).toBeNull();
  });

  it("reads the demo's sample data from the copied static files", () => {
    expect(sampleUrl("console", true)).toBe("/sample/console.json");
    expect(sampleUrl("scenarios", false)).toBe("/api/sample/scenarios");
  });

  it("answers the Models and Sources pages with an empty instance and refuses changes", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
    const api = createMockApi();

    expect(await api.models.providers()).toEqual([]);
    expect((await api.models.tiers()).embedding.backend).toBe("local");
    expect((await api.models.classifier()).enabled).toBe(false);
    expect(await api.sources.list()).toEqual([]);
    await expect(api.models.addProvider({ kind: "openai", api_key: "x" } as never)).rejects.toThrow(/needs the api/);
    await expect(api.sources.create({} as never)).rejects.toThrow(/needs the api/);
    vi.unstubAllGlobals();
  });
});
