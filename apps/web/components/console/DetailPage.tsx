"use client";

// A console detail page: a back button, the title with its status, a header of actions and the page
// body, usually two panes (`fc-split`) that stack below 900px. A missing item says so instead of crashing.

import type { ReactNode } from "react";

import { Button } from "@/components/ui/controls";
import { EmptyState, Skeleton, StatusPill } from "@/components/ui/feedback";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

type Props = {
  title: ReactNode;
  mono?: boolean;
  titleLang?: string;
  status?: string;
  meta?: ReactNode;
  backLabel?: string;
  onBack: () => void;
  actions?: ReactNode;
  loading: boolean;
  missing?: boolean;
  children?: ReactNode;
};

export function DetailPage({ title, mono, titleLang, status, meta, backLabel, onBack, actions, loading, missing, children }: Props) {
  const { t } = useI18n();
  const back = <Button variant="ghost" iconOnly icon="chevronLeft" label={backLabel ?? t("ui.back")} onClick={onBack} />;
  if (loading) return <div className="fc-page"><Skeleton variant="page" /></div>;
  if (missing)
    return (
      <article className="fc-review">
        <div className="fc-detail-head">{back}</div>
        <div className="fc-page"><EmptyState title={t("ui.notFound")} /></div>
      </article>
    );
  return (
    <article className="fc-review">
      <div className="fc-detail-head">
        {back}
        <h1 className={cx(mono && "fc-mono")} lang={titleLang}>{title}</h1>
        {status ? <StatusPill status={status} /> : null}
        {meta ?? null}
        <span className="fc-spacer" />
        {actions ? <div className="fc-detail-actions">{actions}</div> : null}
      </div>
      {children}
    </article>
  );
}
