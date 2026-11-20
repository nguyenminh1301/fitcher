import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExposureBanner } from "@/components/ui/ExposureBanner";
import { I18nProvider } from "@/lib/i18n/react";

afterEach(cleanup);

describe("exposure banner", () => {
  it("warns, without a way to dismiss it, when the instance is reachable by others", () => {
    render(<I18nProvider initial="en"><ExposureBanner identity={{ user_id: "owner", display_name: "Owner", roles: [], exposed: true }} /></I18nProvider>);

    expect(screen.getByText(/anyone who can reach this address controls fitcher/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows nothing on loopback", () => {
    const { container } = render(<I18nProvider initial="en">
      <ExposureBanner identity={{ user_id: "owner", display_name: "Owner", roles: [], exposed: false }} />
      <ExposureBanner identity={null} />
    </I18nProvider>);

    expect(container.textContent).toBe("");
  });

  it("gives the api's reason when the api refused this browser, such as through a misconfigured reverse proxy", () => {
    const reason = "the request names '127.0.0.1:3000' but came through a reverse proxy (connection: close)";
    render(<I18nProvider initial="en"><ExposureBanner identity={null} refused={reason} /></I18nProvider>);

    expect(screen.getByText("fitcher refused this browser")).toBeTruthy();
    expect(screen.getByText(reason)).toBeTruthy();
  });
});
