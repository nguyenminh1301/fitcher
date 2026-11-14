"use client";

// Sign out, then open the address the api gives. A sign-out the api did not complete leaves the user on
// the page and says so, because the session may still be active.

import { useCallback } from "react";

import { useI18n } from "@/lib/i18n/react";

export function useSignOut(signOut: () => Promise<string>, open: (url: string) => void = (url) => window.location.assign(url)) {
  const { t } = useI18n();
  return useCallback(async () => {
    let url: string;
    try {
      url = await signOut();
    } catch {
      window.alert(t("ui.signOutFailed"));
      return;
    }
    open(url);
  }, [signOut, open, t]);
}
