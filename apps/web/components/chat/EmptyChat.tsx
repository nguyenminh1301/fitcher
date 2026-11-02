"use client";

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";

import { Composer, PackChip } from "./Composer";

/** A new conversation: the question title, the composer and the pack's suggested questions. */
export function EmptyChat() {
  const { t, locale } = useI18n();
  const { api, identity, pack, ask, busy } = useChat();
  const [suggestions, setSuggestions] = useState<{ text: string; lang: string }[]>([]);

  useEffect(() => {
    void api.chat.suggestions().then(setSuggestions);
  }, [api]);

  const firstName = identity?.display_name.split(" ")[0] ?? "";
  return (
    <div className="fc-scroll">
      <div className="fc-hero">
        <h1>{t("ui.heroTitle", { name: firstName })}</h1>
        <p className="fc-hero-sub">{t("ui.heroSub", { pack: pack?.display_name ?? "" })}</p>
        <Composer large running={!!busy} onSend={(text) => void ask(text)} meta={pack ? <PackChip name={pack.name} /> : null} />
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
