"use client";

// The chat app's frame (docs/design/web-app.md): history sidebar with New chat, Search, Pinned, Groups and
// Recent, the conversation menu and dialogs, a resizable and collapsible sidebar that becomes a drawer
// below 768px, the top bar with the conversation title, and the account menu.

import { useEffect, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { Button, TextField } from "@/components/ui/controls";
import { Dialog, Menu, type MenuItem } from "@/components/ui/overlay";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
import type { Conversation, ConversationGroup } from "@/lib/api/conversations";
import { recency, useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";

import { AccountMenu } from "./AccountMenu";
import { SearchDialog } from "./SearchDialog";

const SIDE_MIN = 220;
const SIDE_MAX = 440;
const SIDE_DEFAULT = 272;

type MenuState = { anchor: HTMLElement; items: MenuItem[]; align: "start" | "end"; label: string } | null;
type DialogState = { kind: "rename-conv" | "rename-group" | "delete-conv" | "delete-group"; id: string } | null;

export function ChatLayout({ children, onConsole, onSignOut }: { children: ReactNode; onConsole?: () => void; onSignOut?: () => void }) {
  const { t } = useI18n();
  const { api, conversations, groups, activeId, navigate, refresh, now } = useChat();
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [width, setWidth] = useState(SIDE_DEFAULT);
  const [menu, setMenu] = useState<MenuState>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [draftName, setDraftName] = useState("");
  const [search, setSearch] = useState(false);
  const [sections, setSections] = useState({ pinned: true, groups: true, recent: true });
  const [closedGroups, setClosedGroups] = useState<Set<string>>(new Set());

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setMenu(null);
        setSearch(true);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const groupOf = (id: string | null) => groups.find((group) => group.id === id);
  const current = conversations.find((item) => item.id === activeId) ?? null;
  const currentGroup = current ? groupOf(current.group_id) : undefined;

  async function patch(id: string, change: Parameters<typeof api.conversations.update>[1]) {
    await api.conversations.update(id, change);
    await refresh();
  }

  function open(id: string | null) {
    navigate(id);
    setDrawer(false);
    setSearch(false);
  }

  async function newGroup(): Promise<ConversationGroup> {
    const group = await api.conversations.createGroup(t("ui.groupNameDefault"));
    await refresh();
    return group;
  }

  function startRename(kind: "conv" | "group", id: string) {
    const name = kind === "conv" ? conversations.find((item) => item.id === id)?.title : groupOf(id)?.name;
    setDraftName(name ?? "");
    setDialog({ kind: kind === "conv" ? "rename-conv" : "rename-group", id });
  }

  async function saveRename() {
    const name = draftName.trim();
    if (!dialog || !name) return;
    if (dialog.kind === "rename-conv") await api.conversations.update(dialog.id, { title: name });
    else await api.conversations.renameGroup(dialog.id, name);
    setDialog(null);
    await refresh();
  }

  async function confirmDelete() {
    if (!dialog) return;
    if (dialog.kind === "delete-conv") {
      await api.conversations.remove(dialog.id);
      if (activeId === dialog.id) navigate(null);
    } else {
      await api.conversations.removeGroup(dialog.id);
    }
    setDialog(null);
    await refresh();
  }

  function conversationMenu(anchor: HTMLElement, item: Conversation, align: "start" | "end" = "end") {
    if (menu?.anchor === anchor) return setMenu(null);
    const items: MenuItem[] = [
      { icon: item.pinned ? "pinOff" : "pin", label: t(item.pinned ? "ui.unpin" : "ui.pin"), shortcut: "P", onSelect: () => void patch(item.id, { pinned: !item.pinned }) },
      { icon: "pencil", label: t("ui.rename"), shortcut: "R", onSelect: () => startRename("conv", item.id) },
      {
        icon: "folder",
        label: t("ui.moveToGroup"),
        sub: [
          ...groups.map((group) => ({ icon: "folder", label: group.name, checked: item.group_id === group.id, onSelect: () => void patch(item.id, { group_id: group.id }) })),
          { separator: true },
          {
            icon: "folderPlus",
            label: t("ui.newGroup"),
            onSelect: async () => {
              const group = await newGroup();
              await patch(item.id, { group_id: group.id });
              startRename("group", group.id);
            },
          },
        ],
      },
      ...(item.group_id ? [{ icon: "folderMinus", label: t("ui.removeFromGroup"), onSelect: () => void patch(item.id, { group_id: null }) }] : []),
      { separator: true },
      { icon: "trash", label: t("ui.del"), shortcut: "D", danger: true, onSelect: () => setDialog({ kind: "delete-conv", id: item.id }) },
    ];
    setMenu({ anchor, items, align, label: t("ui.chatOptions", { name: item.title }) });
  }

  function groupMenu(anchor: HTMLElement, group: ConversationGroup) {
    if (menu?.anchor === anchor) return setMenu(null);
    setMenu({
      anchor,
      align: "end",
      label: t("ui.groupOptions", { name: group.name }),
      items: [
        { icon: "pencil", label: t("ui.rename"), shortcut: "R", onSelect: () => startRename("group", group.id) },
        { separator: true },
        { icon: "trash", label: t("ui.del"), shortcut: "D", danger: true, onSelect: () => setDialog({ kind: "delete-group", id: group.id }) },
      ],
    });
  }

  function startResize(event: React.PointerEvent) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    const move = (moveEvent: PointerEvent) => setWidth(Math.max(SIDE_MIN, Math.min(SIDE_MAX, startWidth + moveEvent.clientX - startX)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    document.body.style.cursor = "col-resize";
  }

  const item = (conversation: Conversation) => {
    const label = t("ui.chatOptions", { name: conversation.title });
    const menuOpen = menu?.label === label;
    return (
      <li key={conversation.id} className="fc-conv" data-open={menuOpen ? "true" : undefined}>
        <button type="button" className="fc-navitem" aria-current={activeId === conversation.id ? "true" : undefined} title={conversation.title} onClick={() => open(conversation.id)}>
          <span className="fc-navitem-text">{conversation.title}</span>
        </button>
        <button type="button" className="fc-conv-more" aria-label={label} aria-haspopup="menu" aria-expanded={menuOpen} onClick={(event) => conversationMenu(event.currentTarget, conversation)}>
          <Icon name="more" />
        </button>
      </li>
    );
  };

  const head = (key: keyof typeof sections, label: string, extra?: ReactNode) => (
    <div className="fc-sec">
      <button type="button" className="fc-sec-toggle" aria-expanded={sections[key]} onClick={() => setSections({ ...sections, [key]: !sections[key] })}>
        {label}
        <Icon name={sections[key] ? "chevronDown" : "chevronRight"} />
      </button>
      {extra ?? null}
    </div>
  );

  const pinned = conversations.filter((conversation) => conversation.pinned);
  const recent = conversations.filter((conversation) => !conversation.pinned && !groupOf(conversation.group_id));
  const searchItems = conversations.map((conversation) => {
    const group = groupOf(conversation.group_id);
    return {
      id: conversation.id,
      title: conversation.title,
      icon: conversation.pinned ? "pin" : group ? "folder" : "message",
      meta: group ? group.name : t(`ui.when_${recency(conversation.updated_at, now())}`),
    };
  });

  const deleting = dialog?.kind.startsWith("delete") ? dialog : null;

  return (
    <div className="fc-app fc-chat" data-drawer={drawer ? "open" : undefined} data-collapsed={collapsed ? "true" : undefined}>
      <nav className="fc-side" aria-label={t("ui.history")} style={{ width }}>
        <div className="fc-side-head">
          <Logo height={20} />
          <Button variant="ghost" iconOnly icon="panelLeft" label={t("ui.closeSidebar")} className="fc-desk-only" onClick={() => setCollapsed(true)} />
          <Button variant="ghost" iconOnly icon="x" label={t("ui.closeHistory")} className="fc-drawer-only" onClick={() => setDrawer(false)} />
        </div>
        <div className="fc-side-actions">
          <button type="button" className="fc-navitem" onClick={() => open(null)}>
            <Icon name="squarePen" /><span className="fc-navitem-text">{t("ui.newChat")}</span>
          </button>
          <button type="button" className="fc-navitem" aria-haspopup="dialog" onClick={() => setSearch(true)}>
            <Icon name="search" /><span className="fc-navitem-text">{t("ui.search")}</span><kbd className="fc-kbd fc-desk-only">Ctrl K</kbd>
          </button>
        </div>
        <div className="fc-side-scroll">
          {pinned.length ? (
            <section>{head("pinned", t("ui.pinned"))}{sections.pinned ? <ul className="fc-navlist">{pinned.map(item)}</ul> : null}</section>
          ) : null}
          <section>
            {head("groups", t("ui.groups"), (
              <Button variant="ghost" size="sm" iconOnly icon="folderPlus" label={t("ui.newGroup")} onClick={async () => startRename("group", (await newGroup()).id)} />
            ))}
            {sections.groups ? (
              <ul className="fc-navlist">
                {groups.map((group) => {
                  const members = conversations.filter((conversation) => conversation.group_id === group.id && !conversation.pinned);
                  const isOpen = !closedGroups.has(group.id);
                  const label = t("ui.groupOptions", { name: group.name });
                  return (
                    <li key={group.id}>
                      <div className="fc-conv" data-open={menu?.label === label ? "true" : undefined}>
                        <button
                          type="button"
                          className="fc-navitem"
                          aria-expanded={isOpen}
                          onClick={() => {
                            const next = new Set(closedGroups);
                            if (isOpen) next.add(group.id);
                            else next.delete(group.id);
                            setClosedGroups(next);
                          }}
                        >
                          <Icon name="folder" /><span className="fc-navitem-text">{group.name}</span><span className="fc-navitem-count">{members.length}</span>
                        </button>
                        <button type="button" className="fc-conv-more" aria-label={label} aria-haspopup="menu" onClick={(event) => groupMenu(event.currentTarget, group)}>
                          <Icon name="more" />
                        </button>
                      </div>
                      {isOpen ? (members.length ? <ul className="fc-navlist fc-navlist-nested">{members.map(item)}</ul> : <p className="fc-nav-empty">{t("ui.emptyGroup")}</p>) : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </section>
          <section>
            {head("recent", t("ui.recent"))}
            {sections.recent
              ? (["today", "week", "month"] as const).map((bucket) => {
                  const list = recent.filter((conversation) => recency(conversation.updated_at, now()) === bucket);
                  if (!list.length) return null;
                  return (
                    <div key={bucket}>
                      <div className="fc-navgroup">{t(`ui.when_${bucket}`)}</div>
                      <ul className="fc-navlist">{list.map(item)}</ul>
                    </div>
                  );
                })
              : null}
          </section>
        </div>
        <div className="fc-side-foot">
          <AccountMenu onConsole={onConsole ?? (() => window.location.assign("/console"))} onSignOut={onSignOut} />
        </div>
        <div
          className="fc-side-resize fc-desk-only"
          role="separator"
          aria-orientation="vertical"
          aria-label={t("ui.resizeSidebar")}
          aria-valuenow={width}
          aria-valuemin={SIDE_MIN}
          aria-valuemax={SIDE_MAX}
          tabIndex={0}
          onPointerDown={startResize}
          onDoubleClick={() => setWidth(SIDE_DEFAULT)}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            setWidth(Math.max(SIDE_MIN, Math.min(SIDE_MAX, width + (event.key === "ArrowRight" ? 16 : -16))));
          }}
        />
      </nav>
      <div className="fc-main">
        <header className="fc-top">
          <Button variant="ghost" iconOnly icon="menu" label={t("ui.openHistory")} className="fc-drawer-only" aria-expanded={drawer} onClick={() => setDrawer(true)} />
          {collapsed ? <Button variant="ghost" iconOnly icon="panelLeft" label={t("ui.openSidebar")} className="fc-desk-only" onClick={() => setCollapsed(false)} /> : null}
          {collapsed ? <Button variant="ghost" iconOnly icon="squarePen" label={t("ui.newChat")} className="fc-desk-only" onClick={() => open(null)} /> : null}
          {current ? (
            <div className="fc-crumb">
              {currentGroup ? (
                <>
                  <span className="fc-crumb-group fc-hide-sm">{currentGroup.name}</span>
                  <span className="fc-crumb-sep fc-hide-sm" aria-hidden>/</span>
                </>
              ) : null}
              <button type="button" className="fc-title-btn" aria-haspopup="menu" aria-label={t("ui.chatOptions", { name: current.title })} onClick={(event) => conversationMenu(event.currentTarget, current, "start")}>
                {current.pinned ? <Icon name="pin" /> : null}
                <span>{current.title}</span>
                <Icon name="chevronDown" />
              </button>
            </div>
          ) : (
            <span className="fc-spacer" />
          )}
          <SampleDataBadge feature="chat" />
          <Button variant="ghost" iconOnly icon="squarePen" label={t("ui.newChat")} className="fc-drawer-only" onClick={() => open(null)} />
        </header>
        {children}
      </div>
      {drawer ? <div className="fc-drawer-scrim" onClick={() => setDrawer(false)} /> : null}
      <Menu anchor={menu?.anchor ?? null} items={menu?.items ?? []} align={menu?.align} label={menu?.label} width={240} onClose={() => setMenu(null)} />
      <SearchDialog open={search} items={searchItems} onClose={() => setSearch(false)} onPick={open} />
      <Dialog
        open={!!dialog && dialog.kind.startsWith("rename")}
        title={t("ui.rename")}
        onClose={() => setDialog(null)}
        actions={
          <>
            <Button onClick={() => setDialog(null)}>{t("ui.cancel")}</Button>
            <Button variant="primary" disabled={!draftName.trim()} onClick={() => void saveRename()}>{t("ui.save")}</Button>
          </>
        }
      >
        <form onSubmit={(event) => { event.preventDefault(); void saveRename(); }}>
          <TextField label={t("ui.name")} value={draftName} data-autofocus onChange={(event) => setDraftName(event.target.value)} />
        </form>
      </Dialog>
      <Dialog
        open={!!deleting}
        tone="danger"
        title={deleting?.kind === "delete-group" ? t("ui.deleteGroupTitle", { name: groupOf(deleting.id)?.name ?? "" }) : t("ui.deleteChatTitle")}
        onClose={() => setDialog(null)}
        actions={
          <>
            <Button onClick={() => setDialog(null)}>{t("ui.cancel")}</Button>
            <Button variant="danger" icon="trash" onClick={() => void confirmDelete()}>{t("ui.del")}</Button>
          </>
        }
      >
        {deleting?.kind === "delete-group" ? t("ui.deleteGroupText") : t("ui.deleteChatText")}
      </Dialog>
    </div>
  );
}
