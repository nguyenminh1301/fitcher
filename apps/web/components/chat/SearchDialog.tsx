"use client";

import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import { EmptyState } from "@/components/ui/feedback";
import { Overlay } from "@/components/ui/overlay";
import { useI18n } from "@/lib/i18n/react";
import { fold } from "@/lib/text";

export type SearchItem = { id: string; title: string; meta?: string; icon?: string };

/** The conversation search popup (also Ctrl K): filters as you type; arrows and Enter open a result. */
export function SearchDialog({ open, items, onPick, onClose }: { open: boolean; items: SearchItem[]; onPick: (id: string) => void; onClose: () => void }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const listId = useId();

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
    }
  }, [open]);

  const wanted = fold(query);
  const shown = items.filter((item) => !wanted || fold(item.title).includes(wanted) || fold(item.meta ?? "").includes(wanted));
  const current = Math.min(selected, shown.length - 1);

  function onKey(event: KeyboardEvent) {
    if (event.key === "ArrowDown" && shown.length) {
      event.preventDefault();
      setSelected((current + 1) % shown.length);
    } else if (event.key === "ArrowUp" && shown.length) {
      event.preventDefault();
      setSelected((current - 1 + shown.length) % shown.length);
    } else if (event.key === "Enter" && shown[current]) {
      event.preventDefault();
      onPick(shown[current].id);
    }
  }

  return (
    <Overlay open={open} onClose={onClose} className="fc-search" label={t("ui.search")}>
      <div className="fc-search-head">
        <Icon name="search" size="lg" />
        <input
          data-autofocus
          className="fc-search-input"
          type="text"
          role="combobox"
          aria-expanded
          aria-controls={listId}
          aria-activedescendant={shown[current] ? `${listId}-${current}` : undefined}
          aria-label={t("ui.searchPlaceholder")}
          placeholder={t("ui.searchPlaceholder")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setSelected(0);
          }}
          onKeyDown={onKey}
        />
        <Button variant="ghost" iconOnly icon="x" label={t("ui.cancel")} onClick={onClose} />
      </div>
      {shown.length ? (
        <ul id={listId} role="listbox" aria-label={t("ui.history")} className="fc-search-list">
          {shown.map((item, index) => (
            <li
              key={item.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === current}
              className="fc-search-row"
              onMouseEnter={() => setSelected(index)}
              onClick={() => onPick(item.id)}
            >
              <Icon name={item.icon ?? "message"} />
              <span className="fc-navitem-text">{item.title}</span>
              {item.meta ? <span className="fc-search-meta">{item.meta}</span> : null}
              <span className="fc-search-enter" aria-hidden>{index === current ? <Icon name="cornerDownLeft" /> : null}</span>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState icon="searchX" title={t("ui.noResults")} />
      )}
    </Overlay>
  );
}
