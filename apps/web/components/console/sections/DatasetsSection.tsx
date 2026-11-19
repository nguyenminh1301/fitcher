"use client";

// Datasets (DECISIONS §15): a read-only view of the active pack's datasets, the tables fitcher may query. A
// dataset opens on its columns with their type, role and description. They change only when the pack is built
// again.

import { useCallback, useState } from "react";

import { DetailPage } from "@/components/console/DetailPage";
import { StatusLabel } from "@/components/console/kit";
import { ListPage } from "@/components/console/ListPage";
import type { DatasetView } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

export function DatasetsSection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { data, failed } = useLoad(useCallback(() => api.datasets.list(), [api]));
  const [open, setOpen] = useState<string | null>(null);
  const dataset = data?.find((item) => item.id === open);
  if (open) return <DatasetDetail dataset={dataset} onBack={() => setOpen(null)} />;
  return (
    <ListPage section="datasets" loading={!data} failed={failed}>
      <section className="box" aria-labelledby="datasets-title">
        <div className="box-head"><h2 id="datasets-title" className="box-title">{t("ui.nav_datasets")}</h2></div>
        <div style={{ overflowX: "auto" }}>
          <table className="tbl tbl-cards">
            <thead><tr><th>{t("ui.name")}</th><th>{t("ui.description")}</th><th>{t("ui.grain")}</th><th>{t("ui.timeColumn")}</th></tr></thead>
            <tbody>
              {(data ?? []).map((item) => (
                <tr key={item.id}>
                  <td><button type="button" className="src-link" onClick={() => setOpen(item.id)}>{item.id}</button></td>
                  <td data-label={t("ui.description")} lang={langOf(item.description)}>{item.description}</td>
                  <td data-label={t("ui.grain")}>{item.grain}</td>
                  <td data-label={t("ui.timeColumn")}>{item.time_column ? <span className="fc-mono">{item.time_column}</span> : <span className="fc-muted">{t("datasetsPage.noTime")}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </ListPage>
  );
}

function DatasetDetail({ dataset, onBack }: { dataset?: DatasetView; onBack: () => void }) {
  const { t } = useI18n();
  return (
    <DetailPage feature="datasets" title={dataset?.id} mono backLabel={t("ui.nav_datasets")} onBack={onBack} loading={false} missing={!dataset}
      description={dataset ? (dataset.time_column
        ? t("datasetsPage.summary", { description: dataset.description, grain: dataset.grain, time: dataset.time_column })
        : t("datasetsPage.summaryNoTime", { description: dataset.description, grain: dataset.grain })) : null}>
      {dataset ? (
        <section className="box" aria-labelledby="columns-title">
          <div className="box-head"><h2 id="columns-title" className="box-title">{t("ui.columns")}</h2></div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead><tr><th>{t("ui.name")}</th><th>{t("ui.colType")}</th><th>{t("ui.colRole")}</th><th>{t("ui.description")}</th></tr></thead>
              <tbody>
                {dataset.columns.map((column) => (
                  <tr key={column.name}>
                    <td><span className="fc-mono">{column.name}</span></td>
                    <td>{t(`datasetsPage.type_${column.type}`) === `datasetsPage.type_${column.type}` ? <span className="fc-mono">{column.type}</span> : t(`datasetsPage.type_${column.type}`)}</td>
                    <td><StatusLabel tone={null}>{t(`datasetsPage.role_${column.role}`) === `datasetsPage.role_${column.role}` ? column.role : t(`datasetsPage.role_${column.role}`)}</StatusLabel></td>
                    <td><span className="fc-muted" lang={langOf(column.description)}>{column.description}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </DetailPage>
  );
}
