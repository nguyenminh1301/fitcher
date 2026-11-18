"use client";

// A console detail page: a link back to its list, the title with its labels and actions, and the page body,
// usually two columns (`split`) that stack on a narrow screen. A missing item says so instead of crashing.

import type { ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Empty, StatusLabel } from "@/components/console/kit";
import { Skeleton } from "@/components/ui/feedback";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
import type { Feature } from "@/lib/api/client";
import { useChat } from "@/lib/chat/ChatContext";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

type Props = {
  /** The api feature the page reads, which decides its Sample data badge. */
  feature: Feature;
  title: ReactNode;
  mono?: boolean;
  titleLang?: string;
  /** Labels next to the title, such as the item's kind and status. */
  labels?: ReactNode;
  /** A status word of the api, shown as a label next to the title. */
  status?: string;
  /** A line under the title. */
  description?: ReactNode;
  /** Anything else next to the title. */
  meta?: ReactNode;
  backLabel?: string;
  onBack: () => void;
  actions?: ReactNode;
  loading: boolean;
  missing?: boolean;
  children?: ReactNode;
};

export function DetailPage({ feature, title, mono, titleLang, labels, status, description, meta, backLabel, onBack, actions, loading, missing, children }: Props) {
  const { t } = useI18n();
  const { sources } = useChat();
  const back = (
    <a className="back" href="#" onClick={(event) => { event.preventDefault(); onBack(); }}>
      <Icon name="arrowLeft" />{backLabel ?? t("ui.back")}
    </a>
  );
  if (loading) return <div className="cs-page"><Skeleton variant="page" /></div>;
  if (missing) return <div className="cs-page">{back}<div className="box"><Empty title={t("ui.notFound")} /></div></div>;
  return (
    <div className="cs-page">
      {back}
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="title-row">
            <h1 className={cx("page-title", mono && "fc-mono")} lang={titleLang}>{title}</h1>
            {labels ?? null}
            {status ? <StatusLabel status={status}>{t(`ui.${status}`)}</StatusLabel> : null}
            {meta ?? null}
            <SampleDataBadge feature={feature} sources={sources} />
          </div>
          {description ? <p className="page-desc">{description}</p> : null}
        </div>
        {actions ? <div className="toolbar">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}
