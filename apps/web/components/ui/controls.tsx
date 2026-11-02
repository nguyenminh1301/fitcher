"use client";

// Buttons, fields and choosers of the design system (Primer anatomy, fc- classes from components.css).

import { useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent, type ReactNode, type TextareaHTMLAttributes } from "react";

import { Icon } from "@/components/brand/Icon";
import { cx } from "@/lib/cx";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg" | "xl";
  icon?: string;
  iconRight?: string;
  iconOnly?: boolean;
  label?: string;
  meta?: string;
  block?: boolean;
};

export function Button({ variant = "secondary", size = "md", icon, iconRight, iconOnly, label, meta, block, className, children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      aria-label={iconOnly ? label : undefined}
      title={iconOnly ? label : undefined}
      {...rest}
      className={cx("fc-btn", `fc-btn-${variant}`, size !== "md" && `fc-btn-${size}`, block && "fc-btn-block", iconOnly && "fc-iconbtn", className)}
    >
      {icon ? <Icon name={icon} spin={icon === "loader"} /> : null}
      {iconOnly ? null : children}
      {meta ? <span className="fc-btn-meta">{meta}</span> : null}
      {iconRight ? <Icon name={iconRight} /> : null}
    </button>
  );
}

type FieldCommon = { label?: string; icon?: string; help?: string; error?: string; className?: string };
export type TextFieldProps = FieldCommon &
  ((InputHTMLAttributes<HTMLInputElement> & { multiline?: false }) | (TextareaHTMLAttributes<HTMLTextAreaElement> & { multiline: true }));

export function TextField(props: TextFieldProps) {
  const { label, icon, help, error, className, multiline, ...rest } = props;
  const id = useId();
  const helpId = `${id}-help`;
  const shared = { id, className: "fc-input", "aria-invalid": error ? true : undefined, "aria-describedby": error || help ? helpId : undefined };
  return (
    <div className={cx("fc-field", className)}>
      {label ? <label className="fc-field-label" htmlFor={id}>{label}</label> : null}
      <div className="fc-input-wrap">
        {icon ? <Icon name={icon} /> : null}
        {multiline ? (
          <textarea {...shared} {...(rest as TextareaHTMLAttributes<HTMLTextAreaElement>)} />
        ) : (
          <input {...shared} {...(rest as InputHTMLAttributes<HTMLInputElement>)} />
        )}
      </div>
      {error ? (
        <span id={helpId} className="fc-field-error"><Icon name="alert" />{error}</span>
      ) : help ? (
        <span id={helpId} className="fc-field-help">{help}</span>
      ) : null}
    </div>
  );
}

export function Checkbox({ label, checked, disabled, onChange }: { label: ReactNode; checked?: boolean; disabled?: boolean; onChange?: (checked: boolean) => void }) {
  return (
    <label className="fc-check">
      <input type="checkbox" checked={!!checked} disabled={disabled} onChange={(event) => onChange?.(event.target.checked)} />
      {label}
    </label>
  );
}

export type ChipProps = ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean; size?: "sm"; icon?: string; count?: ReactNode };

/** A toggle or suggestion pill; a selected chip shows a check mark, never colour alone. */
export function Chip({ selected, size, icon, count, className, children, ...rest }: ChipProps) {
  return (
    <button type="button" aria-pressed={selected === undefined ? undefined : selected} {...rest} className={cx("fc-chip", size === "sm" && "fc-chip-sm", className)}>
      {icon || selected ? <Icon name={selected ? "check" : (icon as string)} /> : null}
      {children}
      {count !== undefined ? <span className="fc-chip-count">{count}</span> : null}
    </button>
  );
}

export type Tab = { id: string; label: string; count?: number };

/** Underline tabs; arrow keys, Home and End move the selection. */
export function Tabs({ tabs, value, onChange, label }: { tabs: Tab[]; value: string; onChange: (id: string) => void; label?: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(event: KeyboardEvent, index: number) {
    const moves: Record<string, number> = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 };
    if (!(event.key in moves)) return;
    event.preventDefault();
    const next = moves[event.key];
    refs.current[next]?.focus();
    onChange(tabs[next].id);
  }
  return (
    <div className="fc-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(element) => { refs.current[index] = element; }}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className="fc-tab"
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKey(event, index)}
          >
            {tab.label}
            {tab.count !== undefined ? <span className="fc-counter">{tab.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

/** A segmented control: one choice of a few, as radio buttons. */
export function Segmented({ options, value, onChange, label, size }: { options: [string, ReactNode][]; value: string; onChange: (value: string) => void; label?: string; size?: "sm" }) {
  return (
    <div className={cx("fc-seg", size === "sm" && "fc-seg-sm")} role="radiogroup" aria-label={label}>
      {options.map(([key, content]) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} className="fc-seg-btn" onClick={() => onChange(key)}>
          {content}
        </button>
      ))}
    </div>
  );
}
