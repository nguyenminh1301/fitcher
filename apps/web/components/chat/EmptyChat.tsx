"use client";

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useChat } from "@/lib/chat/ChatContext";
import { takeQuestion } from "@/lib/chat/pendingQuestion";
import { useI18n } from "@/lib/i18n/react";

import { Composer, PackPicker } from "./Composer";

/** No pack is active yet, so there is nothing to ask about: point to what comes first, a model or the data. */
function NoPack() {
  const { t } = useI18n();
  const { api } = useChat();
  // Unknown until the providers are read; a failed read points to the data, as before.
  const [model, setModel] = useState<boolean | null>(null);
  useEffect(() => {
    void api.models.providers().then((list) => setModel(list.length > 0)).catch(() => setModel(true));
  }, [api]);
  if (model === null) return null;
  const [title, text, action, href, icon] = model
    ? [t("ui.noPackTitle"), t("ui.noPackText"), t("ui.noPackAction"), "/console/sources", "database"]
    : [t("ui.noModelTitle"), t("ui.noModelText"), t("ui.noModelAction"), "/console/models", "cpu"];
  return (
    <div className="fc-scroll">
      <div className="fc-hero">
        <h1>{title}</h1>
        <p className="fc-hero-sub">{text}</p>
        <div style={{ display: "flex", justifyContent: "center" }}><a className="fc-btn fc-btn-primary" href={href}><Icon name={icon} />{action}</a></div>
      </div>
    </div>
  );
}

/** A new conversation: the question title, the composer and the pack's suggested questions. */
export function EmptyChat() {
  const { t, locale } = useI18n();
  const { api, identity, pack, ask, busy, loaded } = useChat();
  const [suggestions, setSuggestions] = useState<{ text: string; lang: string }[]>([]);

  // The current source's questions, read again when another source is chosen.
  const packName = pack?.name;
  useEffect(() => {
    void api.chat.suggestions().then(setSuggestions);
  }, [api, packName]);

  // A question picked in the setup is asked as soon as the pack is known.
  useEffect(() => {
    if (!loaded || !pack) return;
    const question = takeQuestion();
    if (question) void ask(question);
  }, [loaded, pack, ask]);

  const firstName = identity?.display_name.split(" ")[0] ?? "";
  if (loaded && !pack) return <NoPack />;
  return (
    <div className="fc-scroll">
      <div className="fc-hero">
        <h1>{firstName ? t("ui.heroTitle", { name: firstName }) : t("ui.heroTitleAnonymous")}</h1>
        <p className="fc-hero-sub">{t("ui.heroSub", { pack: pack?.display_name ?? "" })}</p>
        <Composer large running={!!busy} onSend={(text) => void ask(text)} meta={pack ? <PackPicker fallback={pack.name} /> : null} />
        {suggestions.length ? (
          <div>
            <h2 className="fc-navgroup" style={{ margin: 0, padding: "0 var(--base-size-12) var(--base-size-4)" }}>{t("ui.suggested")}</h2>
            <ul className="fc-suggest">
              {suggestions.map((suggestion) => (
                <li key={suggestion.text}>
                  <button type="button" className="fc-suggest-row" lang={suggestion.lang} onClick={() => void ask(suggestion.text)}>
                    <Icon name="message" />
                    <span>{suggestion.text}</span>
                    {suggestion.lang !== locale ? <span className="fc-suggest-lang">{suggestion.lang.toUpperCase()}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
