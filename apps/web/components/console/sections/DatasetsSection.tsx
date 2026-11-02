"use client";

// Datasets (DECISIONS §15): a read-only view of the compiled pack's datasets, their columns, types and
// roles, and which pack roles may read each one.

import { useCallback, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { DetailPage } from "@/components/console/DetailPage";
import { ListPage, ListRow, RecordTable } from "@/components/console/ListPage";
import type { DatasetView } from "@/lib/api/provisional";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

export function RoleChips({ roles }: { roles: string[] }) {
  return (
    <span className="fc-row" style={{ gap: "var(--base-size-4)" }}>
      {roles.map((role) => <span key={role} className="fc-pill fc-pill-neutral fc-mono">{role}</span>)}
    </span>
  );
}

export function DatasetsSection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { data, failed } = useLoad(useCallback(() => api.datasets.list(), [api]));
  const [open, setOpen] = useState<string | null>(null);
  const dataset = data?.find((item) => item.id === open);
  if (open) return <DatasetDetail dataset={dataset} onBack={() => setOpen(null)} />;
  return (
    <ListPage section="datasets" loading={!data} failed={failed}>
      <section className="fc-card">
        <div className="fc-card-head">
          <h2 className="fc-group-label"><Icon name="fileText" />datasets.yaml</h2>
          <span className="fc-counter" style={{ marginRight: "var(--base-size-8)" }}>{data?.length ?? 0}</span>
        </div>
        <ul className="fc-list">
          {(data ?? []).map((item) => (
            <ListRow key={item.id} mono title={item.id} sub={item.description} subLang={langOf(item.description)} onOpen={() => setOpen(item.id)}
              side={<span className="fc-hide-sm fc-muted" style={{ fontSize: 12 }}>{`${t("ui.columns")}: ${item.columns.length}`}</span>} />
          ))}
        </ul>
      </section>
    </ListPage>
  );
}

function DatasetDetail({ dataset, onBack }: { dataset?: DatasetView; onBack: () => void }) {
  const { t } = useI18n();
  return (
    <DetailPage title={dataset?.id} mono onBack={onBack} loading={false} missing={!dataset}>
      {dataset ? (
        <div className="fc-page">
          <dl className="fc-kv">
            <dt>{t("ui.description")}</dt>
            <dd lang={langOf(dataset.description)}>{dataset.description}</dd>
            <dt>{t("ui.grain")}</dt>
            <dd>{dataset.grain}</dd>
            <dt>{t("ui.timeColumn")}</dt>
            <dd><code className="fc-code">{dataset.time_column}</code></dd>
            <dt>{t("ui.allowedRoles")}</dt>
            <dd><RoleChips roles={dataset.readable_roles} /></dd>
          </dl>
          <RecordTable
            label={t("ui.columns")}
            title={t("ui.columns")}
            rows={dataset.columns}
            rowKey={(column) => column.name}
            columns={[
              { key: "name", label: t("ui.name"), mono: true },
              { key: "type", label: t("ui.colType"), mono: true },
              { key: "role", label: t("ui.colRole"), mono: true },
              { key: "description", label: t("ui.description"), render: (column) => <span lang={langOf(column.description)}>{column.description}</span> },
            ]}
          />
        </div>
      ) : null}
    </DetailPage>
  );
}
