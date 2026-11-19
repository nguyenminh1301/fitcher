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

/**
 * A modal dialog: a title with a close button, the body and a row of actions. ``wide`` fits a table; on a
 * phone every dialog fills the screen.
 */
export function Dialog({ open, title, tone, actions, onClose, wide, closeLabel = "Close", children }: {
  open: boolean; title: string; tone?: "danger"; actions?: ReactNode; onClose?: () => void; wide?: boolean; closeLabel?: string; children?: ReactNode;
}) {
  const titleId = useId();
  return (
    <Overlay open={open} onClose={onClose} className={cx("dlg", wide && "dlg-wide")} role={tone === "danger" ? "alertdialog" : "dialog"} labelledBy={titleId}>
      <div className="dlg-head">
        <h2 className="dlg-title" id={titleId}>{title}</h2>
        {onClose ? (
          <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={closeLabel} onClick={onClose}><Icon name="x" /></button>
        ) : null}
      </div>
      {children ? <div className="dlg-body">{children}</div> : null}
      {actions ? <div className="dlg-foot">{actions}</div> : null}
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

/**
 * An anchored action menu, kept inside the app frame; arrow keys move, Escape closes, a shortcut letter picks.
 * An item with ``sub`` opens its own panel beside the menu on hover, click, Enter or the right arrow, with the item's
 * label as its heading; the left arrow or Escape goes back to the item. Where neither side has room the panel opens
 * over the menu instead.
 */
export function Menu({ anchor, items, onClose, align, width, header, label }: MenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const subRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const [open, setOpen] = useState<{ index: number; item: MenuItem; focus: boolean } | null>(null);
  const [subPosition, setSubPosition] = useState<{ left: number; top: number } | null>(null);
  const root = anchor ? appRoot(anchor) : null;

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
  }, [anchor, root, align]);

  useLayoutEffect(() => {
    if (!open || !ref.current || !subRef.current || !root) {
      setSubPosition(null);
      return;
    }
    const rootBox = root.getBoundingClientRect();
    const menuBox = ref.current.getBoundingClientRect();
    const itemBox = ref.current.querySelector<HTMLElement>(`[data-menu-index="${open.index}"]`)?.getBoundingClientRect() ?? menuBox;
    const subWidth = subRef.current.offsetWidth;
    const subHeight = subRef.current.offsetHeight;
    const right = menuBox.right - rootBox.left + 4;
    const leftSide = menuBox.left - rootBox.left - subWidth - 4;
    const left = right + subWidth <= rootBox.width - 8 ? right : leftSide >= 8 ? leftSide : menuBox.left - rootBox.left;
    const top = Math.max(8, Math.min(itemBox.top - rootBox.top - 8, rootBox.height - subHeight - 8));
    setSubPosition({ left, top });
  }, [open, root]);

  useEffect(() => {
    if (!anchor) return;
    const element = ref.current;
    if (!open) element?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    function inside(target: EventTarget | null) {
      const node = target as Node;
      return Boolean(element?.contains(node) || subRef.current?.contains(node));
    }
    function down(event: MouseEvent) {
      if (!inside(event.target) && !anchor?.contains(event.target as Node)) onClose();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !inside(event.target)) onClose();
    }
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", escape);
    };
    // Focus moves to the first item only when the menu opens, not when a panel closes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor, onClose]);

  useEffect(() => {
    if (open?.focus && subPosition) subRef.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
  }, [open, subPosition]);

  if (!anchor || !root) return null;

  function pick(item: MenuItem, index?: number, focus = true) {
    if (item.disabled) return;
    if (item.sub && index !== undefined) {
      setOpen({ index, item, focus });
      return;
    }
    onClose(true);
    item.onSelect?.();
  }

  function closeSub() {
    const index = open?.index;
    setOpen(null);
    if (index !== undefined) ref.current?.querySelector<HTMLElement>(`[data-menu-index="${index}"]`)?.focus();
  }

  function moveFocus(event: KeyboardEvent, container: HTMLElement | null) {
    const list = Array.from(container?.querySelectorAll<HTMLElement>("[role=menuitem]:not([aria-disabled=true])") ?? []);
    const index = list.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      list[(index + 1) % list.length]?.focus();
      return true;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      list[(index - 1 + list.length) % list.length]?.focus();
      return true;
    }
    return false;
  }

  function shortcut(event: KeyboardEvent, list: MenuItem[], fromRoot: boolean) {
    if (event.ctrlKey || event.metaKey || event.key.length !== 1) return;
    const index = list.findIndex((item) => item.shortcut?.toLowerCase() === event.key.toLowerCase());
    if (index >= 0) {
      event.preventDefault();
      pick(list[index], fromRoot ? index : undefined);
    }
  }

  function onKey(event: KeyboardEvent) {
    if (moveFocus(event, ref.current)) return;
    const focused = (document.activeElement as HTMLElement | null)?.dataset.menuIndex;
    const item = focused === undefined ? undefined : items[Number(focused)];
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      anchor?.focus();
    } else if (event.key === "ArrowRight" && item?.sub) {
      event.preventDefault();
      pick(item, Number(focused));
    } else if (event.key === "Tab") {
      onClose();
    } else {
      shortcut(event, items, true);
    }
  }

  function onSubKey(event: KeyboardEvent) {
    if (moveFocus(event, subRef.current)) return;
    if (event.key === "Escape" || event.key === "ArrowLeft") {
      event.preventDefault();
      event.stopPropagation();
      closeSub();
    } else if (event.key === "Tab") {
      onClose();
    } else if (open?.item.sub) {
      shortcut(event, open.item.sub, false);
    }
  }

  const row = (item: MenuItem, index: number, inSub: boolean) => {
    if (item.separator) return <div key={`s${index}`} className="fc-menu-sep" role="separator" />;
    if (item.node) return <div key={`n${index}`}>{item.node}</div>;
    const expanded = !inSub && item.sub ? open?.index === index : undefined;
    return (
      <button
        key={index}
        type="button"
        role="menuitem"
        data-menu-index={inSub ? undefined : index}
        aria-haspopup={!inSub && item.sub ? "menu" : undefined}
        aria-expanded={expanded}
        aria-disabled={item.disabled ? true : undefined}
        className={cx("fc-menu-item", item.danger && "fc-menu-danger", item.checked && "fc-menu-checked", expanded && "fc-menu-open")}
        onClick={() => pick(item, inSub ? undefined : index)}
        onMouseEnter={inSub ? undefined : () => (item.sub ? !item.disabled && setOpen({ index, item, focus: false }) : open && setOpen(null))}
      >
        {item.icon ? <Icon name={item.icon} /> : null}
        <span className="fc-navitem-text">{item.label}</span>
        {item.checked ? <Icon name="check" /> : null}
        {item.shortcut ? <kbd className="fc-kbd">{item.shortcut}</kbd> : null}
        {!inSub && item.sub ? <Icon name="chevronRight" /> : null}
      </button>
    );
  };

  return createPortal(
    <>
      <div
        ref={ref}
        className="fc-menu"
        role="menu"
        aria-label={label}
        onKeyDown={onKey}
        style={{ left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? "visible" : "hidden", width }}
      >
        {header ?? null}
        {items.map((item, index) => row(item, index, false))}
      </div>
      {open?.item.sub ? (
        <div
          ref={subRef}
          className="fc-menu fc-submenu"
          role="menu"
          aria-label={open.item.label}
          onKeyDown={onSubKey}
          style={{ left: subPosition?.left ?? 0, top: subPosition?.top ?? 0, visibility: subPosition ? "visible" : "hidden" }}
        >
          <div className="fc-menu-heading" aria-hidden="true">{open.item.label}</div>
          {open.item.sub.map((item, index) => row(item, index, true))}
        </div>
      ) : null}
    </>,
    root,
  );
}
