"use client";

import { useState, type MouseEvent } from "react";

import { Icon } from "@/components/brand/Icon";
import { StatusPill } from "@/components/ui/feedback";
import { Menu, type MenuItem } from "@/components/ui/overlay";
import { isSample } from "@/lib/api/sources";
import { hasConsole, useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";
import { useTheme, type Theme } from "@/lib/theme";

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

/** Who is signed in, the interface language and theme, the console entry for console roles (or the
 *  chat app's, inside the console), and sign out. While sign-in runs on sample data it also offers the
 *  pack's demo identities. */
export function AccountMenu({ onConsole, onChat, onSignOut, compact }: { onConsole?: () => void; onChat?: () => void; onSignOut?: () => void; compact?: boolean }) {
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  const { identity, identities, sources, switchIdentity } = useChat();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  if (!identity) return null;
  const roles = identity.roles;

  const items: MenuItem[] = [
    { icon: "globe", label: t("ui.language"), sub: (["en", "vi"] as const).map((code) => ({ label: t(`language.${code}`), checked: locale === code, onSelect: () => setLocale(code) })) },
    { icon: "sun", label: t("theme.label"), sub: (["system", "light", "dark"] as Theme[]).map((value) => ({ label: t(`theme.${value}`), checked: theme === value, onSelect: () => setTheme(value) })) },
  ];
  if (isSample("auth", sources) && identities.length > 1) {
    items.push({ separator: true }, { node: <div className="fc-navgroup">{t("sample.identity")}</div> });
    for (const option of identities) {
      items.push({ icon: "user", label: `${option.display_name} · ${option.roles.join(", ")}`, checked: option.user_id === identity.user_id, onSelect: () => void switchIdentity(option.user_id) });
    }
  }
  items.push({ separator: true });
  if (onChat) items.push({ icon: "message", label: t("ui.chatApp"), onSelect: onChat });
  else if (hasConsole(roles) && onConsole) items.push({ icon: "layout", label: t("ui.console"), onSelect: onConsole });
  // Individual mode has no sign-in, so there is nothing to sign out of.
  if (identity.mode !== "individual") items.push({ icon: "logout", label: t("ui.signOut"), onSelect: onSignOut });

  const header = (
    <>
      <div className="fc-menu-who">
        <span className="fc-avatar" aria-hidden>{initials(identity.display_name)}</span>
        <div style={{ minWidth: 0 }}><b>{identity.display_name}</b>{identity.user_id}</div>
      </div>
      <div className="fc-menu-row"><span className="fc-muted">{t("ui.role")}</span><StatusPill status="neutral">{roles.join(", ")}</StatusPill></div>
      <div className="fc-menu-sep" role="separator" />
    </>
  );

  const label = `${t("ui.account")}: ${identity.display_name}`;
  const toggle = (event: MouseEvent<HTMLElement>) => setAnchor(anchor ? null : event.currentTarget);
  return (
    <>
      {compact ? (
        <button type="button" className="fc-avatar" aria-label={label} aria-haspopup="menu" aria-expanded={!!anchor} onClick={toggle}>
          {initials(identity.display_name)}
        </button>
      ) : (
        <button
          type="button"
          className="fc-acct"
          aria-label={label}
          aria-haspopup="menu"
          aria-expanded={!!anchor}
          onClick={toggle}
        >
          <span className="fc-avatar" aria-hidden>{initials(identity.display_name)}</span>
          <span className="fc-acct-text">{identity.display_name}<small>{roles.join(", ")}</small></span>
          <Icon name="chevronsUpDown" />
        </button>
      )}
      <Menu anchor={anchor} align={compact ? "end" : "start"} width={280} label={t("ui.account")} header={header} items={items} onClose={() => setAnchor(null)} />
    </>
  );
}
