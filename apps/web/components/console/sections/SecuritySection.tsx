"use client";

// The Security page (DECISIONS §9, §15): set, change or remove the optional owner password. Without one the
// instance answers this computer only; with one every browser signs in, and an instance reachable from other
// machines (FITCHER_ALLOWED_HOSTS) needs one and keeps it.

import { type FormEvent, useCallback, useState } from "react";

import { ListPage } from "@/components/console/ListPage";
import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { errorText } from "@/lib/api/errorText";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

const MIN_LENGTH = 8;

const message = errorText;

export function SecuritySection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { data: status, failed, reload } = useLoad(useCallback(() => api.owner.status(), [api]));
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  const mismatch = again.length > 0 && next !== again;
  const short = next.length > 0 && next.length < MIN_LENGTH;

  async function run(action: () => Promise<void>, done: string) {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      setCurrent("");
      setNext("");
      setAgain("");
      setNotice({ tone: "success", text: done });
      await reload();
    } catch (cause) {
      setNotice({ tone: "danger", text: message(cause) });
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    void run(() => api.owner.setPassword(next, status?.password_set ? current : undefined),
      status?.password_set ? t("owner.changed") : t("owner.set"));
  }

  return (
    <ListPage section="security" loading={!status} failed={failed}>
      {status ? (
        <div className="fc-stack" style={{ gap: "var(--base-size-16)" }}>
          {status.exposed && !status.password_set ? <WarningBanner tone="warning">{t("owner.exposedNeedsPassword")}</WarningBanner> : null}
          <WarningBanner tone={status.password_set ? "success" : "info"}>
            {status.password_set ? t("owner.statusOn") : t("owner.statusOff")}
          </WarningBanner>
          {notice ? <WarningBanner tone={notice.tone}>{notice.text}</WarningBanner> : null}
          <form className="fc-card" aria-label={status.password_set ? t("owner.changeTitle") : t("owner.setTitle")} onSubmit={save}>
            <div className="fc-card-head"><h2 className="fc-card-title">{status.password_set ? t("owner.changeTitle") : t("owner.setTitle")}</h2></div>
            <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
              {status.password_set ? (
                <TextField label={t("owner.currentPassword")} type="password" autoComplete="current-password" value={current}
                  disabled={busy} onChange={(event) => setCurrent(event.target.value)} />
              ) : null}
              <TextField label={t("owner.newPassword")} type="password" autoComplete="new-password" value={next} disabled={busy}
                help={t("owner.rule", { count: MIN_LENGTH })} error={short ? t("owner.tooShort", { count: MIN_LENGTH }) : undefined}
                onChange={(event) => setNext(event.target.value)} />
              <TextField label={t("owner.repeatPassword")} type="password" autoComplete="new-password" value={again} disabled={busy}
                error={mismatch ? t("owner.mismatch") : undefined} onChange={(event) => setAgain(event.target.value)} />
              <div>
                <Button type="submit" variant="primary"
                  disabled={busy || next.length < MIN_LENGTH || next !== again || (status.password_set && !current)}>
                  {status.password_set ? t("owner.change") : t("owner.setButton")}
                </Button>
              </div>
            </div>
          </form>
          {status.password_set ? (
            <section className="fc-card" aria-label={t("owner.removeTitle")}>
              <div className="fc-card-head"><h2 className="fc-card-title">{t("owner.removeTitle")}</h2></div>
              <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
                <p className="fc-muted" style={{ margin: 0 }}>{t("owner.removeHint")}</p>
                <div>
                  <Button disabled={busy || !current} onClick={() => void run(() => api.owner.removePassword(current), t("owner.removed"))}>
                    {t("owner.remove")}
                  </Button>
                </div>
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </ListPage>
  );
}
