"use client";

// The label next to an action that calls the models: "Uses paid AI" unless every chain is chosen from free
// models only (``auto_free``), where the same action costs nothing and the label says so.

import { useEffect, useState } from "react";

import { useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";

export function useAiCostLabel(): { text: string; paid: boolean } {
  const { t } = useI18n();
  const { api } = useChat();
  const [free, setFree] = useState(false);
  useEffect(() => {
    let live = true;
    void api.models.tiers().then((view) => { if (live) setFree(view.mode === "auto_free"); }).catch(() => undefined);
    return () => { live = false; };
  }, [api]);
  return free ? { text: t("ui.freeAi"), paid: false } : { text: t("ui.paidAi"), paid: true };
}
