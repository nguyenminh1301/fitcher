"use client";

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useChat } from "@/lib/chat/ChatContext";
import { takeQuestion } from "@/lib/chat/pendingQuestion";
import { useI18n } from "@/lib/i18n/react";

import { Composer, PackPicker } from "./Composer";

/** No pack is active yet, so there is nothing to ask about: point to connecting data and building the pack. */
function NoPack() {
  const { t } = useI18n();
  return (
    <div className="fc-scroll">
      <div className="fc-hero">
        <h1>{t("ui.noPackTitle")}</h1>
        <p className="fc-hero-sub">{t("ui.noPackText")}</p>
        <div style={{ display: "flex", justifyContent: "center" }}><a className="fc-btn fc-btn-primary" href="/console/sources"><Icon name="database" />{t("ui.noPackAction")}</a></div>
      </div>
    </div>
  );
}

/** A new conversation: the question title, the composer and the pack's suggested questions. */
export function EmptyChat() {
  const { t, locale } = useI18n();
  const { api, identity, pack, ask, busy, loaded } = useChat();
  const [suggestions, setSuggestions] = useState<{ text: string; lang: string }[]>([]);

  useEffect(() => {
    void api.chat.suggestions().then(setSuggestions);
  }, [api]);

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
