"use client";

// The owner's menu, shared by the chat and the console: who this is ("Owner", on this computer or signed in),
// the theme and language, the chat, the console and the Security page, and signing out once an owner password
// is set.

import { useCallback, useEffect, useState, type MouseEvent } from "react";

import { Icon } from "@/components/brand/Icon";
import { Segmented } from "@/components/ui/controls";
import { Menu, type MenuItem } from "@/components/ui/overlay";
import { useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";
import { useTheme, type Theme } from "@/lib/theme";

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

export function AccountMenu({ onConsole, onChat, onSecurity }: { onConsole?: () => void; onChat?: () => void; onSecurity?: () => void }) {
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  const { api } = useChat();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  // Signing out is offered only once the owner has set a password; without one there is no session.
  const [password, setPassword] = useState(false);
  // Read again whenever the menu opens: a password set or removed on the Security page changes what it offers.
  const refresh = useCallback(() => {
    void api.owner.status().then((status) => setPassword(status.password_set && status.signed_in)).catch(() => setPassword(false));
  }, [api]);
  useEffect(refresh, [refresh]);
  const name = t("owner.name");
  const where = password ? t("owner.signedIn") : t("owner.thisComputer");

  const items: MenuItem[] = [
    { icon: "globe", label: t("ui.language"), sub: (["vi", "en"] as const).map((code) => ({ label: t(`language.${code}`), checked: locale === code, onSelect: () => setLocale(code) })) },
  ];
  items.push({ separator: true });
  if (onChat) items.push({ icon: "message", label: t("console.chat"), onSelect: onChat });
  if (onConsole) items.push({ icon: "home", label: t("ui.console"), onSelect: onConsole });
  if (onSecurity) items.push({ icon: "lock", label: t("owner.securityItem"), onSelect: onSecurity });
  if (password) {
    items.push({ separator: true }, { icon: "logout", label: t("owner.signOut"), onSelect: () => void api.owner.signOut().finally(() => window.location.assign("/sign-in")) });
  }

  const header = (
    <>
      <div className="menu-who">
        <span className="avatar" aria-hidden><Icon name="user" /></span>
        <div style={{ minWidth: 0 }}><div className="acct-name">{name}</div><div className="acct-sub">{where}</div></div>
      </div>
      <div className="menu-row">
        <span className="fc-muted">{t("theme.label")}</span>
        <Segmented size="sm" iconOnly label={t("theme.label")} value={theme} onChange={(value) => setTheme(value as Theme)}
          options={[["system", <Icon key="system" name="monitor" />, t("theme.system")], ["light", <Icon key="light" name="sun" />, t("theme.light")],
            ["dark", <Icon key="dark" name="moon" />, t("theme.dark")]]} />
      </div>
      <div className="fc-menu-sep" role="separator" />
    </>
  );

  const label = t("owner.menu");
  const toggle = (event: MouseEvent<HTMLElement>) => {
    if (!anchor) refresh();
    setAnchor(anchor ? null : event.currentTarget);
  };
  return (
    <>
      <button type="button" className="acct" aria-label={label} aria-haspopup="menu" aria-expanded={!!anchor} onClick={toggle}>
        <span className="avatar" aria-hidden><Icon name="user" /></span>
        <span className="acct-text"><span className="acct-name">{name}</span><span className="acct-sub">{where}</span></span>
        <Icon name="chevronsUpDown" />
      </button>
      <Menu anchor={anchor} align="start" width="anchor" label={label} header={header} items={items} onClose={() => setAnchor(null)} />
    </>
  );
}
