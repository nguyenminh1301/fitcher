"use client";

// The Security page (DECISIONS §9, §15): set, change or remove the optional owner password. Without one the
// instance answers this computer only; with one every browser signs in. An instance reachable from other machines
// (FITCHER_ALLOWED_HOSTS) needs a password, says so until one is set, and keeps it while it stays reachable. A
// forgotten password cannot be recovered, and the page says so.

import { type FormEvent, useCallback, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { ListPage } from "@/components/console/ListPage";
import { errorText } from "@/lib/api/errorText";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

// The api's minimum (app/auth/owner.py): an instance open to other machines answers them with this password alone.
const MIN_LENGTH = 12;

/** How hard a new password is to guess: long enough, then longer or mixing kinds of characters. */
export function passwordStrength(password: string): "short" | "fair" | "strong" {
  if (password.length < MIN_LENGTH) return "short";
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((kind) => kind.test(password)).length;
  return password.length >= 16 || kinds >= 3 ? "strong" : "fair";
}

function Field({ id, label, value, onChange, autoComplete, disabled, help, error }: {
  id: string; label: string; value: string; onChange: (value: string) => void; autoComplete: string; disabled?: boolean; help?: string; error?: string;
}) {
  const described = [help ? `${id}-help` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="fc-field">
      <label className="fc-field-label" htmlFor={id}>{label}</label>
      <input id={id} className="fc-input" type="password" autoComplete={autoComplete} value={value} disabled={disabled}
        aria-invalid={error ? true : undefined} aria-describedby={described} onChange={(event) => onChange(event.target.value)} />
      {help ? <span className="fc-field-help" id={`${id}-help`}>{help}</span> : null}
      {error ? <span className="fc-field-error" id={`${id}-error`} role="alert"><Icon name="alert" />{error}</span> : null}
    </div>
  );
}

export function SecuritySection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { data: status, failed, reload } = useLoad(useCallback(() => api.owner.status(), [api]));
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const mismatch = again.length > 0 && next !== again;
  const short = next.length > 0 && next.length < MIN_LENGTH;
  const strength = passwordStrength(next);

  async function run(action: () => Promise<void>, done: string) {
    setBusy(true);
    setNotice(null);
    try {
      await action();
      setCurrent("");
      setNext("");
      setAgain("");
      setNotice({ ok: true, text: done });
      await reload();
    } catch (cause) {
      setNotice({ ok: false, text: errorText(cause) });
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    void run(() => api.owner.setPassword(next, status?.password_set ? current : undefined),
      status?.password_set ? t("owner.changed") : t("owner.set"));
  }

  const set = Boolean(status?.password_set);
  const title = set ? t("owner.changeTitle") : t("owner.setTitle");
  const line = notice ? (
    <p role={notice.ok ? "status" : "alert"} className={notice.ok ? "notice-ok" : "fc-field-error"}>
      <Icon name={notice.ok ? "check" : "alert"} />{notice.text}
    </p>
  ) : null;
  return (
    <ListPage section="security" loading={!status} failed={failed}>
      {status ? (
        <>
          {status.exposed && !set ? (
            <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" /><div>{t("owner.exposedNeedsPassword")}</div></div>
          ) : null}
          <p style={{ margin: 0 }}>{set ? t("owner.statusOn") : t("owner.statusOff")}</p>
          <form className="box" aria-labelledby="password-title" onSubmit={save}>
            <div className="box-head"><h2 id="password-title" className="box-title">{title}</h2></div>
            <div className="box-body">
              {set ? <Field id="owner-current" label={t("owner.currentPassword")} autoComplete="current-password" value={current} disabled={busy} onChange={setCurrent} /> : null}
              <Field id="owner-new" label={t("owner.newPassword")} autoComplete="new-password" value={next} disabled={busy}
                help={t("owner.rule", { count: MIN_LENGTH })} error={short ? t("owner.tooShort", { count: MIN_LENGTH }) : undefined} onChange={setNext} />
              {next.length > 0 && strength !== "short" ? (
                <p className="fc-field-help" role="status" style={{ margin: 0 }}>{t(`owner.strength_${strength}`)}</p>
              ) : null}
              <Field id="owner-again" label={t("owner.repeatPassword")} autoComplete="new-password" value={again} disabled={busy}
                error={mismatch ? t("owner.mismatch") : undefined} onChange={setAgain} />
              <div>
                <button type="submit" className="fc-btn fc-btn-primary" disabled={busy || next.length < MIN_LENGTH || next !== again || (set && !current)}>
                  {set ? t("owner.change") : t("owner.setButton")}
                </button>
              </div>
              {line}
            </div>
          </form>
          {set ? (
            <section className="box" aria-labelledby="remove-title">
              <div className="box-head"><h2 id="remove-title" className="box-title">{t("owner.removeTitle")}</h2></div>
              <div className="box-body">
                <p className="fc-muted" style={{ margin: 0 }}>{t("owner.removeHint")}</p>
                <div>
                  <button type="button" className="fc-btn" disabled={busy || !current || status.exposed}
                    aria-describedby={status.exposed ? "remove-why" : undefined}
                    onClick={() => void run(() => api.owner.removePassword(current), t("owner.removed"))}>{t("owner.remove")}</button>
                  {status.exposed ? <span className="fc-field-help" id="remove-why" style={{ marginLeft: 8 }}>{t("owner.removeExposed")}</span> : null}
                </div>
              </div>
            </section>
          ) : null}
          <p className="fc-field-help forgot-line"><Icon name="info" />{t("owner.forgottenConsole")}</p>
          <QuestionLimit />
        </>
      ) : null}
    </ListPage>
  );
}

/** How many questions the instance answers at once (app/api/limits.py); more wait their turn in order. */
function QuestionLimit() {
  const { t } = useI18n();
  const { api } = useChat();
  const { data } = useLoad(useCallback(() => api.owner.limits(), [api]));
  const [value, setValue] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  const shown = value ?? String(data.concurrent_questions);
  const parsed = Number(shown);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 64;
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      const saved = await api.owner.setLimits(parsed);
      setValue(String(saved.concurrent_questions));
      setNotice({ ok: true, text: t("limits.saved") });
    } catch (error) {
      setNotice({ ok: false, text: errorText(error) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="box" aria-labelledby="limits-title" onSubmit={(event) => void save(event)}>
      <div className="box-head"><h2 id="limits-title" className="box-title">{t("limits.title")}</h2></div>
      <div className="box-body">
        <div className="fc-field">
          <label className="fc-field-label" htmlFor="limits-questions">{t("limits.label")}</label>
          <input id="limits-questions" className="fc-input" type="number" min={1} max={64} inputMode="numeric" style={{ maxWidth: 120 }}
            value={shown} disabled={busy} aria-describedby="limits-help" aria-invalid={valid ? undefined : true}
            onChange={(event) => { setValue(event.target.value); setNotice(null); }} />
          <span className="fc-field-help" id="limits-help">{t("limits.help")}</span>
        </div>
        <div><button type="submit" className="fc-btn" disabled={busy || !valid || parsed === data.concurrent_questions}>{t("limits.save")}</button></div>
        {notice ? (
          <p role={notice.ok ? "status" : "alert"} className={notice.ok ? "notice-ok" : "fc-field-error"}>
            <Icon name={notice.ok ? "check" : "alert"} />{notice.text}
          </p>
        ) : null}
      </div>
    </form>
  );
}
