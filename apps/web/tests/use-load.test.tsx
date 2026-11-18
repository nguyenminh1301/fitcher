import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useLoad } from "@/lib/console/useLoad";

afterEach(cleanup);

function Page({ load }: { load: () => Promise<string> }) {
  const { data, failed } = useLoad(load);
  return <p>{failed ? "failed" : data ?? "loading"}</p>;
}

describe("useLoad", () => {
  it("shows what the load returned", async () => {
    render(<Page load={async () => "ready"} />);

    expect(await screen.findByText("ready")).toBeTruthy();
  });

  it("changes nothing when the load finishes after the page has left", async () => {
    let finish: (value: string) => void = () => {};
    const load = () => new Promise<string>((resolve) => { finish = resolve; });
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<Page load={load} />);

    unmount();
    await act(async () => finish("late"));

    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});
