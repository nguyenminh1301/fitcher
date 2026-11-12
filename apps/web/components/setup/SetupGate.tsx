"use client";

// Holds the chat app and the console back while the instance is not set up (DECISIONS §15): an admin is
// sent to /setup, any other user sees a notice. A status that cannot be read lets the app load, so a
// failing setup api never locks the instance.

import { useEffect, useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/Logo";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import { useI18n } from "@/lib/i18n/react";

type Gate = "checking" | "open" | "redirecting" | "notice";

export function SetupGate({ api, redirect, children }: { api: Pick<FitcherApi, "setup" | "auth">; redirect: (path: string) => void; children: ReactNode }) {
  const { t } = useI18n();
  const [gate, setGate] = useState<Gate>("checking");
  useEffect(() => {
    let live = true;
    const decide = async (): Promise<Gate> => {
      try {
        if ((await api.setup.status()).complete) return "open";
        const identity = await api.auth.current();
        return identity?.roles.includes("admin") ? "redirecting" : "notice";
      } catch {
        return "open";
      }
    };
    void decide().then((next) => {
      if (!live) return;
      setGate(next);
      if (next === "redirecting") redirect("/setup");
    });
    return () => {
      live = false;
    };
    // The gate decides once per page load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (gate === "open") return <>{children}</>;
  if (gate !== "notice") return null;
  return (
    <main style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "var(--base-size-24)", padding: "var(--base-size-48) var(--base-size-16)" }}>
      <Logo height={24} />
      <div style={{ width: "min(480px, 100%)" }}><WarningBanner tone="info">{t("setup.notice")}</WarningBanner></div>
    </main>
  );
}
