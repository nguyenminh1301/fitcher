"use client";

import { useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Finch, Logo } from "@/components/brand/Logo";
import { Button, Checkbox, Chip, Segmented, Tabs, TextField } from "@/components/ui/controls";
import { EmptyState, Skeleton, StatusPill, Toast, Tooltip, WarningBanner } from "@/components/ui/feedback";
import { Dialog, Menu } from "@/components/ui/overlay";
import { Preferences } from "@/components/ui/Preferences";
import { useI18n } from "@/lib/i18n/react";

const STATUSES = ["success", "failed", "denied", "clarify", "draft", "approved", "processing", "indexed", "allow", "deny", "estimate"];

export function Gallery() {
  const { t } = useI18n();
  const [tab, setTab] = useState("items");
  const [segment, setSegment] = useState("all");
  const [checked, setChecked] = useState(true);
  const [dialog, setDialog] = useState(false);
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  return (
    <main className="fc-app fc-stack" style={{ maxWidth: 960, margin: "0 auto", padding: 24, position: "relative" }}>
      <div className="fc-row"><Logo height={32} /><span className="fc-spacer" /><Preferences /></div>
      <section className="fc-row"><Logo variant="symbol" height={24} /><Logo variant="wordmark" height={20} /><Finch /><Finch live size={36} /></section>
      <section className="fc-row">
        <Button variant="primary" icon="arrowUp">{t("ui.send")}</Button>
        <Button>{t("common.cancel")}</Button>
        <Button variant="ghost" icon="copy">{t("ui.copy")}</Button>
        <Button variant="danger" icon="trash">{t("ui.del")}</Button>
        <Button iconOnly icon="more" label="More" onClick={(event) => setMenu(event.currentTarget)} />
        <Tooltip label={t("sample.tooltip")}><Button size="sm" icon="info">{t("sample.badge")}</Button></Tooltip>
      </section>
      <section className="fc-row">
        <Chip>Top 10 products</Chip>
        <Chip selected>{t("ui.approved")}</Chip>
        <Chip size="sm" count={3}>{t("ui.draft")}</Chip>
        <Checkbox label={t("ui.approved")} checked={checked} onChange={setChecked} />
      </section>
      <Tabs label="Review" value={tab} onChange={setTab} tabs={[{ id: "items", label: t("ui.items") }, { id: "proposals", label: t("ui.proposals"), count: 3 }]} />
      <Segmented value={segment} onChange={setSegment} options={[["all", t("ui.all")], ["draft", t("ui.draft")], ["approved", t("ui.approved")]]} />
      <TextField label={t("ui.composerLabel")} placeholder={t("ui.composerPlaceholder")} help={t("ui.composerHint")} icon="search" />
      <section className="fc-row">{STATUSES.map((status) => <StatusPill key={status} status={status} />)}</section>
      <WarningBanner title="Partial data">The data covers 2022-01-02 to 2026-08-18.</WarningBanner>
      <WarningBanner tone="info">{t("sample.tooltip")}</WarningBanner>
      <Toast icon="circleCheck" onClose={() => undefined}>{t("common.copied")}</Toast>
      <EmptyState title={t("ui.emptyTitle")}>{t("ui.emptyText")}</EmptyState>
      <Skeleton variant="answer" />
      <section className="fc-row"><Icon name="shieldCheck" /><Icon name="database" /><Icon name="chartGrouped" size="lg" /><Icon name="loader" spin /></section>
      <Button onClick={() => setDialog(true)}>Open dialog</Button>
      <Dialog open={dialog} title={t("ui.deleteDocTitle", { name: "report.pdf" })} tone="danger" onClose={() => setDialog(false)}
        actions={<><Button onClick={() => setDialog(false)}>{t("common.cancel")}</Button><Button variant="danger" onClick={() => setDialog(false)}>{t("ui.del")}</Button></>}>
        {t("ui.deleteDocText")}
      </Dialog>
      <Menu anchor={menu} onClose={() => setMenu(null)} items={[{ icon: "pin", label: "Pin" }, { icon: "pencil", label: t("ui.edit") }, { separator: true }, { icon: "trash", label: t("ui.del"), danger: true }]} />
    </main>
  );
}
