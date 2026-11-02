"use client";

// Modal layers and menus: portalled into the app frame, Escape closes, focus is trapped and returned.

import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Icon } from "@/components/brand/Icon";
import { cx } from "@/lib/cx";

const FOCUSABLE = "button:not([disabled]), input:not([disabled]), textarea, select, [tabindex='0']";

function appRoot(element: Element | null): HTMLElement | null {
  if (typeof document === "undefined") return null;
  return (element?.closest(".fc-app") as HTMLElement | null) ?? document.body;
}

function trapFocus(container: HTMLElement, event: globalThis.KeyboardEvent) {
  const focusable = container.querySelectorAll<HTMLElement>(FOCUSABLE);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

type OverlayProps = { open: boolean; onClose?: () => void; className?: string; role?: string; labelledBy?: string; label?: string; children: ReactNode };

export function Overlay({ open, onClose, className, role = "dialog", labelledBy, label, children }: OverlayProps) {
  const anchor = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [root, setRoot] = useState<HTMLElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => setRoot(appRoot(anchor.current)), []);

  useEffect(() => {
    if (!open || !root) return;
    const previous = document.activeElement as HTMLElement | null;
    const element = panel.current;
    const first = element?.querySelector<HTMLElement>("[data-autofocus]") ?? element?.querySelector<HTMLElement>("button, input, textarea, [tabindex]");
    first?.focus();
    function onKey(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && close.current) {
        event.stopPropagation();
        close.current();
      }
      if (event.key === "Tab" && element) trapFocus(element, event);
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [open, root]);

  const layer =
    open && root
      ? createPortal(
          <div
            className={cx("fc-scrim", root === document.body && "fc-scrim-fixed")}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) onClose?.();
            }}
          >
            <div ref={panel} className={className} role={role} aria-modal="true" aria-labelledby={labelledBy} aria-label={label}>
              {children}
            </div>
          </div>,
          root,
        )
      : null;
  return (
    <>
      <span ref={anchor} hidden />
      {layer}
    </>
  );
}

export function Dialog({ open, title, tone, actions, onClose, children }: { open: boolean; title: string; tone?: "danger"; actions?: ReactNode; onClose?: () => void; children?: ReactNode }) {
  const titleId = useId();
  return (
    <Overlay open={open} onClose={onClose} className="fc-dialog" role={tone === "danger" ? "alertdialog" : "dialog"} labelledBy={titleId}>
      <h2 id={titleId}>{title}</h2>
      {children ? <div className="fc-dialog-body">{children}</div> : null}
      <div className="fc-dialog-actions">{actions}</div>
    </Overlay>
  );
}

export type MenuItem = {
  icon?: string;
  label?: string;
  onSelect?: () => void;
  shortcut?: string;
  danger?: boolean;
  checked?: boolean;
  disabled?: boolean;
  sub?: MenuItem[];
  separator?: boolean;
  node?: ReactNode;
};

export type MenuProps = { anchor: HTMLElement | null; items: MenuItem[]; onClose: (selected?: boolean) => void; align?: "start" | "end"; width?: number; header?: ReactNode; label?: string };

/** An anchored action menu, kept inside the app frame; arrow keys move, Escape closes, a shortcut letter picks. */
export function Menu({ anchor, items, onClose, align, width, header, label }: MenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const [submenu, setSubmenu] = useState<MenuItem | null>(null);
  const root = anchor ? appRoot(anchor) : null;
  const shown = submenu?.sub ?? items;

  useLayoutEffect(() => {
    if (!anchor || !ref.current || !root) return;
    const anchorBox = anchor.getBoundingClientRect();
    const rootBox = root.getBoundingClientRect();
    const menuWidth = ref.current.offsetWidth;
    const menuHeight = ref.current.offsetHeight;
    let left = align === "start" ? anchorBox.left - rootBox.left : anchorBox.right - rootBox.left - menuWidth;
    left = Math.max(8, Math.min(left, rootBox.width - menuWidth - 8));
    let top = anchorBox.bottom - rootBox.top + 4;
    if (top + menuHeight > rootBox.height - 8) top = Math.max(8, anchorBox.top - rootBox.top - menuHeight - 4);
    setPosition({ left, top });
  }, [anchor, submenu, root, align]);

  useEffect(() => {
    if (!anchor) return;
    const element = ref.current;
    element?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    function down(event: MouseEvent) {
      if (element && !element.contains(event.target as Node) && !anchor?.contains(event.target as Node)) onClose();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !(element && element.contains(event.target as Node))) onClose();
    }
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", escape);
    };
  }, [anchor, submenu, onClose]);

  if (!anchor || !root) return null;

  function pick(item: MenuItem) {
    if (item.disabled) return;
    if (item.sub) {
      setSubmenu(item);
      return;
    }
    onClose(true);
    item.onSelect?.();
  }

  function onKey(event: KeyboardEvent) {
    const list = Array.from(ref.current?.querySelectorAll<HTMLElement>("[role=menuitem]:not([aria-disabled=true])") ?? []);
    const index = list.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (submenu) setSubmenu(null);
      else {
        onClose();
        anchor?.focus();
      }
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      list[(index + 1) % list.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      list[(index - 1 + list.length) % list.length]?.focus();
    } else if (event.key === "Tab") {
      onClose();
    } else if (!event.ctrlKey && !event.metaKey && event.key.length === 1) {
      const hit = shown.find((item) => item.shortcut?.toLowerCase() === event.key.toLowerCase());
      if (hit) {
        event.preventDefault();
        pick(hit);
      }
    }
  }

  return createPortal(
    <div
      ref={ref}
      className="fc-menu"
      role="menu"
      aria-label={label}
      onKeyDown={onKey}
      style={{ left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? "visible" : "hidden", width }}
    >
      {submenu ? (
        <button type="button" role="menuitem" className="fc-menu-item fc-menu-back" onClick={() => setSubmenu(null)}>
          <Icon name="chevronLeft" />
          {submenu.label}
        </button>
      ) : (header ?? null)}
      {shown.map((item, index) => {
        if (item.separator) return <div key={`s${index}`} className="fc-menu-sep" role="separator" />;
        if (item.node) return <div key={`n${index}`}>{item.node}</div>;
        return (
          <button
            key={index}
            type="button"
            role="menuitem"
            aria-disabled={item.disabled ? true : undefined}
            className={cx("fc-menu-item", item.danger && "fc-menu-danger", item.checked && "fc-menu-checked")}
            onClick={() => pick(item)}
          >
            {item.icon ? <Icon name={item.icon} /> : null}
            <span className="fc-navitem-text">{item.label}</span>
            {item.checked ? <Icon name="check" /> : null}
            {item.shortcut ? <kbd className="fc-kbd">{item.shortcut}</kbd> : null}
            {item.sub ? <Icon name="chevronRight" /> : null}
          </button>
        );
      })}
    </div>,
    root,
  );
}
