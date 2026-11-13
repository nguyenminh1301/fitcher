import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExposureBanner } from "@/components/ui/ExposureBanner";
import { I18nProvider } from "@/lib/i18n/react";

afterEach(cleanup);

describe("exposure banner", () => {
  it("warns, without a way to dismiss it, when an individual instance is reachable by others", () => {
    render(<I18nProvider initial="en"><ExposureBanner identity={{ user_id: "owner", display_name: "Owner", roles: [], mode: "individual", exposed: true }} /></I18nProvider>);

    expect(screen.getByText(/Anyone who can reach this address controls this instance/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows nothing on loopback or in team mode", () => {
    const { container } = render(<I18nProvider initial="en">
      <ExposureBanner identity={{ user_id: "owner", display_name: "Owner", roles: [], mode: "individual", exposed: false }} />
      <ExposureBanner identity={{ user_id: "ana", display_name: "Ana", roles: [], mode: "team" }} />
      <ExposureBanner identity={null} />
    </I18nProvider>);

    expect(container.textContent).toBe("");
  });
});
