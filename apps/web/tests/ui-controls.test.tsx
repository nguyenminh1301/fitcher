import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Button, Tabs } from "@/components/ui/controls";
import { Dialog, Menu } from "@/components/ui/overlay";
import { StatusPill } from "@/components/ui/feedback";
import { I18nProvider } from "@/lib/i18n/react";

afterEach(cleanup);

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <I18nProvider>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <Dialog open={open} title="Delete report.pdf?" onClose={() => setOpen(false)} actions={<Button>Delete</Button>}>
        This can&apos;t be undone.
      </Dialog>
    </I18nProvider>
  );
}

describe("dialog", () => {
  it("moves focus inside, closes on Escape and returns focus to the opener", () => {
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "Open" });
    opener.focus();
    fireEvent.click(opener);

    expect(screen.getByRole("dialog", { name: "Delete report.pdf?" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Delete" }));

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe("tabs", () => {
  it("moves the selection with the arrow keys", () => {
    function Harness() {
      const [value, setValue] = useState("items");
      return <Tabs tabs={[{ id: "items", label: "Items" }, { id: "proposals", label: "Proposals", count: 3 }]} value={value} onChange={setValue} />;
    }
    render(<Harness />);

    fireEvent.keyDown(screen.getByRole("tab", { name: "Items" }), { key: "ArrowRight" });

    expect(screen.getByRole("tab", { name: /Proposals/ }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("menu", () => {
  it("runs the chosen item and closes", () => {
    let chosen = "";
    function Harness() {
      const [anchor, setAnchor] = useState<HTMLElement | null>(null);
      return (
        <>
          <button onClick={(event) => setAnchor(event.currentTarget)}>More</button>
          <Menu anchor={anchor} onClose={() => setAnchor(null)} items={[{ icon: "pin", label: "Pin", onSelect: () => (chosen = "pin") }]} />
        </>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));

    act(() => fireEvent.click(screen.getByRole("menuitem", { name: "Pin" })));

    expect(chosen).toBe("pin");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("status pill", () => {
  it("labels the status in the interface language", () => {
    render(
      <I18nProvider initial="vi">
        <StatusPill status="approved" />
      </I18nProvider>,
    );

    expect(screen.getByText("Đã duyệt")).toBeTruthy();
  });
});
