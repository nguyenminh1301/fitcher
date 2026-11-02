"use client";

// The workspace console (docs/design/web-app.md, Workspace console): a top bar with the pack, the
// navigation grouped by Knowledge, Observe, Quality and Administration, and the open section in a
// panel. The navigation lists only the sections the signed-in roles allow and re-checks them when
// the identity changes; below 768px it becomes a drawer.

import { createContext, Fragment, useCallback, useContext, useEffect, useState, type MouseEvent, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { AccountMenu } from "@/components/chat/AccountMenu";
import { Button } from "@/components/ui/controls";
import { Skeleton, Toast } from "@/components/ui/feedback";
import { useChat } from "@/lib/chat/ChatContext";
import { allowedSections, type SectionGroup } from "@/lib/console/sections";
import { useI18n } from "@/lib/i18n/react";

const GROUP_LABEL: Record<SectionGroup, string> = {
  knowledge: "ui.group_knowledge", observe: "ui.group_observe", quality: "ui.group_quality", administration: "ui.group_admin",
};

type Navigate = (path: string, options?: { replace: boolean }) => void;

type ConsoleState = { toast: (message: string) => void; navigate: Navigate };
const ConsoleContext = createContext<ConsoleState>({ toast: () => undefined, navigate: () => undefined });

/** A section page's way to confirm an action and to open another console page. */
export function useConsole(): ConsoleState {
  return useContext(ConsoleContext);
}

type Props = {
  /** The section key from the URL, or null for ``/console``. */
  section: string | null;
  navigate: Navigate;
  onChat: () => void;
  onSignOut?: () => void;
  children: ReactNode;
};

export function ConsoleLayout({ section, navigate, onChat, onSignOut, children }: Props) {
  const { t } = useI18n();
  const { identity, pack } = useChat();
  const [drawer, setDrawer] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const allowed = identity ? allowedSections(identity.roles) : [];
  const current = allowed.find((item) => item.key === section);
  const firstAllowed = allowed[0]?.path;

  useEffect(() => {
    if (!identity) return;
    if (!firstAllowed) onChat();
    else if (!current) navigate(firstAllowed, { replace: true });
  }, [identity, current, firstAllowed, navigate, onChat]);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 2600);
    return () => clearTimeout(timer);
  }, [message]);

  const toast = useCallback((text: string) => setMessage(text), []);

  function follow(event: MouseEvent, go: () => void) {
    event.preventDefault();
    setDrawer(false);
    go();
  }

  const groups = [...new Set(allowed.map((item) => item.group))];
  return (
    <ConsoleContext.Provider value={{ toast, navigate }}>
      <div className="fc-app fc-console" data-drawer={drawer ? "open" : undefined}>
        <div className="fc-cgrid">
          <header className="fc-ctop">
            <Button variant="ghost" iconOnly icon="menu" label={t("ui.menu")} className="fc-drawer-only" aria-expanded={drawer} onClick={() => setDrawer(true)} />
            <Logo variant="symbol" height={22} className="fc-desk-only" />
            <div className="fc-crumb">
              <span className="fc-crumb-btn" title={t("ui.activePack")}>
                <Icon name="database" />
                <span className="fc-navitem-text">{pack?.display_name ?? ""}</span>
              </span>
            </div>
            <Button variant="ghost" icon="message" className="fc-hide-sm" onClick={onChat}>{t("ui.chatApp")}</Button>
            <AccountMenu compact onChat={onChat} onSignOut={onSignOut} />
          </header>
          <nav className="fc-cnav" aria-label={t("ui.consoleLabel")}>
            <div className="fc-drawer-only fc-cnav-head">
              <Logo height={20} />
              <Button variant="ghost" iconOnly icon="x" label={t("common.close")} onClick={() => setDrawer(false)} />
            </div>
            {groups.map((group) => (
              <Fragment key={group}>
                <div className="fc-navgroup">{t(GROUP_LABEL[group])}</div>
                <ul className="fc-navlist">
                  {allowed.filter((item) => item.group === group).map((item) => (
                    <li key={item.key}>
                      <a href={item.path} className="fc-navitem" aria-current={item.key === section ? "page" : undefined} onClick={(event) => follow(event, () => navigate(item.path))}>
                        <Icon name={item.icon} />
                        <span className="fc-navitem-text">{t(`ui.nav_${item.key}`)}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </Fragment>
            ))}
            <div style={{ flex: 1 }} />
            <a href="/" className="fc-navitem" onClick={(event) => follow(event, onChat)}>
              <Icon name="message" />
              <span className="fc-navitem-text">{t("ui.openChat")}</span>
            </a>
          </nav>
          <main className="fc-panel">{current ? children : <div className="fc-page"><Skeleton variant="page" /></div>}</main>
        </div>
        {drawer ? <div className="fc-drawer-scrim" onClick={() => setDrawer(false)} /> : null}
        {message ? (
          <div className="fc-toast-wrap">
            <Toast icon="check" onClose={() => setMessage(null)}>{message}</Toast>
          </div>
        ) : null}
      </div>
    </ConsoleContext.Provider>
  );
}
