"use client";

// The two flows the Sources page opens on their own page (/console/sources/new and /console/sources/[id]/pack), built from the setup's steps: adding a source (the
// Data step, starting on a file or a database) and building or rebuilding a source's pack (the Start step,
// with the paid model call confirmed first). Both end back on the Sources page. The public demo shows the
// adding flow locked, since it has nothing to connect to.

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { DataStep, type Chosen } from "@/components/setup/DataStep";
import { StartStep } from "@/components/setup/StartStep";
import { DemoLocked } from "@/components/ui/DemoLock";
import { keepQuestion } from "@/lib/chat/pendingQuestion";
import { useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";

function Frame({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const { navigate } = useConsole();
  return (
    <div className="cs-page">
      <a className="back" href="/console/sources" onClick={(event) => { event.preventDefault(); navigate("/console/sources"); }}>
        <Icon name="arrowLeft" />{t("sourcesPage.backToSources")}
      </a>
      <div className="ob-col flow-col">{children}</div>
    </div>
  );
}

function Build({ chosen }: { chosen: Chosen }) {
  const { api } = useChat();
  const { navigate } = useConsole();
  return (
    <StartStep sources={api.sources} chosen={chosen} meta={null} onModel={() => navigate("/console/models")}
      onAsk={(question) => { if (question) keepQuestion(question); window.location.assign("/"); }}
      onConsole={(path) => navigate(path ?? "/console/sources")} />
  );
}

export function AddSourcePage({ kind }: { kind: "file" | "database" }) {
  const { api } = useChat();
  const { navigate } = useConsole();
  const [chosen, setChosen] = useState<Chosen | null>(null);
  return (
    <Frame>
      {chosen ? <Build chosen={chosen} /> : (
        <DemoLocked>
          <DataStep sources={api.sources} meta={null} initial={kind === "database" ? "database" : "choose"}
            onBack={() => navigate("/console/sources")} onChosen={setChosen} />
        </DemoLocked>
      )}
    </Frame>
  );
}

export function BuildPackPage({ id }: { id: string }) {
  const { t } = useI18n();
  const { api } = useChat();
  const [chosen, setChosen] = useState<Chosen | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    void Promise.all([api.sources.list(), api.sources.tables(id)]).then(([list, tables]) => {
      const source = list.find((item) => item.id === id);
      if (!source) return setMissing(true);
      setChosen({ source: { ...source, tables }, tables: tables.filter((table) => table.selected) });
    }).catch(() => setMissing(true));
  }, [api, id]);
  return (
    <Frame>
      {missing ? <p className="fc-muted">{t("ui.notFound")}</p> : chosen ? <Build chosen={chosen} /> : <p className="fc-muted" role="status">…</p>}
    </Frame>
  );
}
