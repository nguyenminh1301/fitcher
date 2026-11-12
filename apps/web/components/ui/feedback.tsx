"use client";

// Status, banners, toasts, tooltips, empty states and loading skeletons of the design system.

import { cloneElement, useId, type ReactElement, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

import { Button } from "./controls";

// status -> [tone, icon]; every status carries an icon and a word, never colour alone.
const STATUS: Record<string, [string, string]> = {
  success: ["success", "circleCheck"], failed: ["danger", "circleX"], denied: ["neutral", "lock"], clarify: ["accent", "help"],
  draft: ["warning", "pencil"], approved: ["success", "circleCheck"], processing: ["muted", "loader"], indexed: ["success", "circleCheck"],
  allow: ["success", "shieldCheck"], deny: ["neutral", "lock"], estimate: ["warning", "info"], warning: ["warning", "alert"],
  definition: ["done", "book"], neutral: ["neutral", "user"], liked: ["success", "thumbsUp"], disliked: ["danger", "thumbsDown"],
  fb_new: ["accent", "info"], proposed: ["done", "clipboardCheck"], dismissed: ["muted", "x"], active: ["success", "circleCheck"],
  disabled: ["neutral", "ban"], passed: ["success", "circleCheck"], belowThreshold: ["danger", "alert"], packEnabled: ["success", "circleCheck"],
  succeeded: ["success", "circleCheck"], rejected: ["warning", "alert"], error: ["danger", "circleX"], running: ["muted", "loader"],
  eligible: ["success", "circleCheck"], ineligible: ["warning", "alert"],
};

export function StatusPill({ status, children }: { status: string; children?: ReactNode }) {
  const { t } = useI18n();
  const [tone, icon] = STATUS[status] ?? ["muted", "circle"];
  return (
    <span className={cx("fc-pill", tone !== "muted" && `fc-pill-${tone}`)}>
      <Icon name={icon} spin={status === "processing"} />
      {children ?? t(`ui.${status}`)}
    </span>
  );
}

export type WarningBannerProps = {
  tone?: "warning" | "info" | "danger" | "success";
  title?: string;
  icon?: string;
  action?: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
  children?: ReactNode;
};

export function WarningBanner({ tone = "warning", title, icon, action, onDismiss, dismissLabel = "Dismiss", children }: WarningBannerProps) {
  const toneIcon = { warning: "alert", info: "info", danger: "circleX", success: "circleCheck" }[tone];
  return (
    <div className={cx("fc-banner", `fc-banner-${tone}`)} role={tone === "danger" ? "alert" : "status"}>
      <Icon name={icon ?? toneIcon} />
      <div className="fc-banner-body">
        {title ? <div className="fc-banner-title">{title}</div> : null}
        {children}
      </div>
      {action ?? null}
      {onDismiss ? <Button variant="ghost" size="sm" iconOnly icon="x" label={dismissLabel} onClick={onDismiss} /> : null}
    </div>
  );
}

export function Toast({ icon, actionLabel, onAction, onClose, children }: { icon?: string; actionLabel?: string; onAction?: () => void; onClose?: () => void; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="fc-toast" role="status" aria-live="polite">
      {icon ? <Icon name={icon} /> : null}
      <span className="fc-toast-msg">{children}</span>
      {actionLabel ? <Button variant="ghost" size="sm" onClick={onAction}>{actionLabel}</Button> : null}
      {onClose ? <Button variant="ghost" size="sm" iconOnly icon="x" label={t("common.close")} onClick={onClose} /> : null}
    </div>
  );
}

/** A description shown on hover and focus, linked to its control by aria-describedby. */
export function Tooltip({ label, open, children }: { label: string; open?: boolean; children: ReactElement<{ "aria-describedby"?: string }> }) {
  const id = useId();
  return (
    <span className="fc-tip-wrap">
      {cloneElement(children, { "aria-describedby": id })}
      <span id={id} role="tooltip" className="fc-tip" data-open={open ? "true" : undefined}>{label}</span>
    </span>
  );
}

export function EmptyState({ title, icon = "searchX", action, children }: { title: string; icon?: string; action?: ReactNode; children?: ReactNode }) {
  return (
    <div className="fc-empty">
      <div className="fc-empty-icon"><Icon name={icon} /></div>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action ?? null}
    </div>
  );
}

export type SkeletonProps = {
  variant?: "text" | "block" | "circle" | "table" | "list" | "answer" | "thread" | "page";
  lines?: number;
  rows?: number;
  height?: number;
  size?: number;
};

const WIDTHS = ["100%", "94%", "72%", "88%", "60%"];

function Line({ width, className }: { width: string; className?: string }) {
  return <span className={cx("fc-skel fc-skel-line", className)} style={{ width }} />;
}
function Lines({ count }: { count: number }) {
  return <div className="fc-skel-lines">{Array.from({ length: count }, (_, i) => <Line key={i} width={WIDTHS[i % WIDTHS.length]} />)}</div>;
}
function Block({ height, className }: { height: number; className?: string }) {
  return <span className={cx("fc-skel fc-skel-block", className)} style={{ height }} />;
}
function TableSkeleton({ rows }: { rows: number }) {
  return (
    <div className="fc-card fc-skel-table">
      <div className="fc-card-head"><Line width="30%" /></div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="fc-skel-row"><Line width="18%" /><Line width="34%" /><Line width="14%" /><Line width="12%" className="fc-skel-end" /></div>
      ))}
    </div>
  );
}

/** Placeholders shaped like the content that is loading; the region is announced once as busy. */
export function Skeleton({ variant = "text", lines = 3, rows = 5, height = 120, size = 28 }: SkeletonProps) {
  const { t } = useI18n();
  const bodies: Record<string, ReactNode> = {
    text: <Lines count={lines} />,
    block: <Block height={height} />,
    circle: <span className="fc-skel fc-skel-circle" style={{ width: size, height: size }} />,
    table: <TableSkeleton rows={rows} />,
    list: (
      <div className="fc-card">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="fc-skel-row">
            <span className="fc-skel-lines" style={{ flex: 1 }}><Line width="40%" /><Line width="70%" /></span>
            <Line width="64px" className="fc-skel-end" />
          </div>
        ))}
      </div>
    ),
    answer: <div className="fc-skel-stack"><Lines count={3} /><Block height={240} className="fc-skel-lg" /><Block height={44} className="fc-skel-lg" /></div>,
    thread: (
      <div className="fc-skel-stack">
        <div className="fc-skel-bubble"><Block height={44} /></div>
        <div className="fc-turn">
          <span className="fc-skel fc-skel-circle" style={{ width: 28, height: 28 }} />
          <div className="fc-skel-stack"><Line width="40%" /><Lines count={3} /><Block height={240} className="fc-skel-lg" /></div>
        </div>
      </div>
    ),
    page: <div className="fc-skel-stack"><Line width="22%" className="fc-skel-title" /><Line width="48%" /><Block height={32} /><TableSkeleton rows={rows} /></div>,
  };
  return <div className="fc-skel-wrap" role="status" aria-busy="true" aria-label={t("common.loading")}>{bodies[variant]}</div>;
}
