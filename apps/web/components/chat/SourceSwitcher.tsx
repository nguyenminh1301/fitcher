"use client";

// The current data source, and a menu to change it (DECISIONS §4): each source whose pack is ready, with its kind
// and how many datasets it answers from, the current one checked, and a way to the Sources page. The chat's
// composer offers it before a conversation's first question; the console's sidebar offers it at its top. Choosing
// a source makes its pack the current one on the api, so the console's pages read it and a new conversation
// starts on it. With one ready source or none it is a plain label.

import { useEffect, useState, type MouseEvent } from "react";

import { Icon } from "@/components/brand/Icon";
import { Menu, type MenuItem } from "@/components/ui/overlay";
import { useChat } from "@/lib/chat/ChatContext";
import type { SourceView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

/** A source whose pack can answer: its pack name, the source's kind and its dataset count. */
export type ReadySource = { name: string; kind: SourceView["kind"]; datasets: number };

export function sourceIcon(kind: SourceView["kind"] | undefined): string {
  return kind === "file" ? "fileText" : "database";
}

/** The sources whose pack is ready; null while they load or when the sources cannot be read. */
export function useReadySources(): ReadySource[] | null {
  const { api } = useChat();
  const [ready, setReady] = useState<ReadySource[] | null>(null);
  useEffect(() => {
    let live = true;
    Promise.resolve().then(() => api.sources.list())
      .then((list) => {
        if (!live) return;
        setReady(list.filter((source) => source.pack?.status === "ready")
          .map((source) => ({ name: source.pack?.name ?? source.id, kind: source.kind, datasets: source.pack?.datasets ?? 0 })));
      })
      .catch(() => { if (live) setReady(null); });
    return () => { live = false; };
  }, [api]);
  return ready;
}

type Props = {
  /** The source shown as current. */
  current: string;
  onChoose: (name: string) => void;
  /** Opens the Sources page; the menu's last item. */
  onManage?: () => void;
  /** `composer`: a chip in the question box; `sidebar`: the console sidebar's first row. */
  variant: "composer" | "sidebar";
  /** Shown when no source is current yet. */
  empty?: string;
};

export function SourceSwitcher({ current, onChoose, onManage, variant, empty }: Props) {
  const { t, formatNumber } = useI18n();
  const ready = useReadySources();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const known = ready?.find((source) => source.name === current);
  const label = current || empty || "";
  const icon = <Icon name={sourceIcon(known?.kind)} />;
  const className = variant === "composer" ? "fc-composer-pack src-switch" : "cs-switch src-switch";
  const choosable = !!ready && ready.length > 0 && (ready.length > 1 || !known || !!onManage);
  if (!choosable) {
    return <span className={className} title={t("ui.activePack")}>{icon}<span className="src-switch-name">{label}</span></span>;
  }

  const items: MenuItem[] = ready.map((source) => ({
    icon: sourceIcon(source.kind),
    label: source.name,
    hint: t("sources.datasetCount", { count: formatNumber(source.datasets) }),
    checked: source.name === current,
    onSelect: () => { if (source.name !== current) onChoose(source.name); },
  }));
  if (onManage) items.push({ separator: true }, { icon: "wrench", label: t("sources.manage"), onSelect: onManage });
  const open = (event: MouseEvent<HTMLElement>) => setAnchor(anchor ? null : event.currentTarget);
  return (
    <>
      <button type="button" className={className} aria-haspopup="menu" aria-expanded={!!anchor}
        aria-label={t("ui.chooseSourceOf", { name: label })} title={t("ui.chooseSource")} onClick={open}>
        {icon}<span className="src-switch-name">{label}</span><Icon name="chevronsUpDown" />
      </button>
      <Menu anchor={anchor} align="start" width={variant === "sidebar" ? "anchor" : 280} label={t("ui.chooseSource")}
        header={<div className="nav-group">{t("sources.answerFrom")}</div>} items={items} onClose={() => setAnchor(null)} />
    </>
  );
}
