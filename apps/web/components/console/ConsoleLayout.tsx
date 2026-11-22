"use client";

// The console (DECISIONS §15): the sidebar on the grey page with the active pack, the pages grouped as Data,
// Quality, Activity and Settings, a link back to the chat and the owner's menu, and the open page on a paper
// panel. Review and Feedback show how many items wait. Below 760px the sidebar becomes a drawer opened from a
// small header. fitcher is a personal app, so every page is listed.

import { createContext, useCallback, useContext, useEffect, useState, type MouseEvent, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { AccountMenu } from "@/components/chat/AccountMenu";
import { SourceSwitcher } from "@/components/chat/SourceSwitcher";
import { Toast } from "@/components/ui/feedback";
import { useChat } from "@/lib/chat/ChatContext";
import { areaOf, AREAS, sectionPath } from "@/lib/console/sections";
import { useI18n } from "@/lib/i18n/react";

type Navigate = (path: string, options?: { replace: boolean }) => void;

type ConsoleState = { toast: (message: string) => void; navigate: Navigate };
const ConsoleContext = createContext<ConsoleState>({ toast: () => undefined, navigate: () => undefined });

/** A section page's way to confirm an action and to open another console page. */
export function useConsole(): ConsoleState {
  return useContext(ConsoleContext);
}

type Props = {
  /** The section key from the URL; "overview" for ``/console``. */
  section: string;
  navigate: Navigate;
  onChat: () => void;
  children: ReactNode;
};

export function ConsoleLayout({ section, navigate, onChat, children }: Props) {
  const { t } = useI18n();
  const { api, pack, choosePack } = useChat();
  // Choosing another source reads every page again, now from that source's pack.
  const [generation, setGeneration] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // How many items wait in Quality: Review's drafts and unreviewed items, and Feedback's dislikes; 0 shows no badge.
  const [waiting, setWaiting] = useState<Record<string, number>>({});
  useEffect(() => {
    let live = true;
    void Promise.all([
      api.review.items().then((items) => items.filter((item) => item.status === "draft" || item.reviewed === false).length).catch(() => 0),
      api.feedbackReview.list().then((rows) => rows.filter((row) => row.rating === "dislike" && !row.proposal).length).catch(() => 0),
    ]).then(([review, feedback]) => { if (live) setWaiting({ quality: review + feedback }); });
    return () => { live = false; };
  }, [api, section, generation]);

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

  const current = areaOf(section).key;
  const link = (key: string) => {
    const area = AREAS.find((entry) => entry.key === key);
    if (!area) return null;
    const path = sectionPath(area.pages[0]);
    const count = waiting[key] ?? 0;
    return (
      <li key={key}>
        <a href={path} className="nav-item" aria-current={key === current ? "page" : undefined} onClick={(event) => follow(event, () => navigate(path))}>
          <Icon name={area.icon} />
          <span className="nav-text">{t(`console.area_${key}`)}</span>
          {count ? <span className="fc-count">{count}<span className="fc-sr"> {t("console.waiting")}</span></span> : null}
        </a>
      </li>
    );
  };

  return (
    <ConsoleContext.Provider value={{ toast, navigate }}>
      <div className="fc-app cs" data-drawer={drawer ? "open" : "closed"}>
        <header className="cs-mhead">
          <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon" aria-label={t("console.openMenu")} aria-expanded={drawer}
            onClick={() => setDrawer(true)}><Icon name="menu" /></button>
          <Logo height={18} />
        </header>
        <nav className="cs-nav" aria-label={t("ui.consoleLabel")}>
          <div className="cs-navtop">
            <SourceSwitcher variant="sidebar" current={pack?.name ?? ""} empty={t("console.noPack")}
              onChoose={(name) => void choosePack(name).then(() => setGeneration((value) => value + 1))}
              onManage={() => navigate("/console/sources")} />
            <span className="cs-navclose">
              <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("console.closeMenu")} onClick={() => setDrawer(false)}>
                <Icon name="x" />
              </button>
            </span>
          </div>
          <ul className="nav-list">{AREAS.map((area) => link(area.key))}</ul>
          <div className="cs-navspace" />
          <a href="/" className="nav-item" onClick={(event) => follow(event, onChat)}>
            <Icon name="message" />
            <span className="nav-text">{t("console.chat")}</span>
          </a>
          <AccountMenu onChat={onChat} onConsole={() => navigate("/console")} onSecurity={() => navigate("/console/security")} />
        </nav>
        <div className="cs-scrim" aria-hidden="true" onClick={() => setDrawer(false)} />
        <main className="cs-main" key={generation}>{children}</main>
        {message ? (
          <div className="fc-toast-wrap">
            <Toast icon="check" onClose={() => setMessage(null)}>{message}</Toast>
          </div>
        ) : null}
      </div>
    </ConsoleContext.Provider>
  );
}
