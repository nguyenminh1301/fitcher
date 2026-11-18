"use client";

// Holds the chat app and the console back while the instance is not set up (DECISIONS §15) and sends the
// owner to /setup, which asks for the owner password first when one is set. A status that cannot be read lets
// the app load, so a failing setup api never locks the instance.

import { useEffect, useState, type ReactNode } from "react";

import type { FitcherApi } from "@/lib/api/client";

export function SetupGate({ api, redirect, children }: { api: Pick<FitcherApi, "setup">; redirect: (path: string) => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    void api.setup.status().then((status) => status.complete).catch(() => true).then((complete) => {
      if (!live) return;
      if (complete) setOpen(true);
      else redirect("/setup");
    });
    return () => {
      live = false;
    };
    // The gate decides once per page load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return open ? <>{children}</> : null;
}
