"use client";

// Users (DECISIONS §9, §15): the realm's users with their pack roles and status. An admin changes a
// user's pack roles (the only roles the api reads or changes) and disables or enables users, never their
// own account; a second tab shows what each pack and console role can open and read.

import { useCallback, useState } from "react";

import { initials } from "@/components/chat/AccountMenu";
import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { Button, Chip, Segmented, Tabs, TextField } from "@/components/ui/controls";
import { StatusPill, WarningBanner } from "@/components/ui/feedback";
import { Dialog } from "@/components/ui/overlay";
import type { UserRow } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { allowedSections } from "@/lib/console/sections";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

const CONSOLE_ROLES = ["pack_reviewer", "admin"];

export function UsersSection() {
  const { t } = useI18n();
  const { api, identity, pack } = useChat();
  const { toast } = useConsole();
  // The datasets a role reads are a hint on the Roles tab; Datasets is a pack_reviewer section, so an admin
  // without that role is refused and the page shows the users without the hint.
  const { data, failed, reload } = useLoad(useCallback(async () => {
    const [users, datasets] = await Promise.all([api.users.list(), api.datasets.list().catch(() => [])]);
    return { users, datasets };
  }, [api]));
  const [tab, setTab] = useState("users");
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("all");
  const [disabling, setDisabling] = useState<UserRow | null>(null);
  const packRoles = pack?.roles ?? [];
  const roles = [...packRoles, ...CONSOLE_ROLES];
  const users = data?.users ?? [];
  const needle = query.trim().toLowerCase();
  const rows = users.filter((user) => (role === "all" || user.roles.includes(role))
    && (!needle || `${user.display_name} ${user.email}`.toLowerCase().includes(needle)));
  const isSelf = (user: UserRow) => user.id === identity?.user_id;

  async function setRoles(user: UserRow, next: string[]) {
    await api.users.setRoles(user.id, next);
    toast(t("ui.roleChanged", { name: user.display_name, role: next.join(", ") || "—" }));
    await reload();
  }

  async function setEnabled(user: UserRow, enabled: boolean) {
    await api.users.setEnabled(user.id, enabled);
    toast(t(enabled ? "ui.userEnabled" : "ui.userDisabled", { name: user.display_name }));
    await reload();
  }

  return (
    <ListPage section="users" loading={!data} failed={failed} skeleton="table">
      <Tabs label={t("ui.nav_users")} value={tab} onChange={setTab}
        tabs={[{ id: "users", label: t("ui.nav_users"), count: users.length }, { id: "roles", label: t("ui.roles"), count: roles.length }]} />
      {tab === "users" ? (
        <>
          <WarningBanner tone="info">{t("ui.usersNote")}</WarningBanner>
          <div className="fc-toolbar">
            <TextField icon="search" type="search" aria-label={t("ui.searchUsers")} placeholder={t("ui.searchUsers")} value={query}
              onChange={(event) => setQuery(event.target.value)} className="fc-tool-field fc-tool-wide" />
            <div className="fc-scroll-x">
              <Segmented label={t("ui.role")} value={role} onChange={setRole} options={[["all", t("ui.allRoles")], ...packRoles.map((item): [string, string] => [item, item])]} />
            </div>
          </div>
          <RecordTable
            key={`${role}|${needle}`}
            label={t("ui.nav_users")}
            rows={rows}
            rowKey={(user) => user.id}
            columns={[
              { key: "name", label: t("ui.name"), render: (user) => (
                <span className="fc-person">
                  <span className="fc-avatar" aria-hidden>{initials(user.display_name)}</span>
                  <span><b>{user.display_name}</b><small>{isSelf(user) ? `${user.email} · ${t("ui.you")}` : user.email}</small></span>
                </span>
              ) },
              { key: "roles", label: t("ui.roles"), render: (user) => (
                <span className="fc-row" role="group" aria-label={t("ui.rolesOf", { name: user.display_name })} style={{ gap: "var(--base-size-4)" }}>
                  {packRoles.map((item) => {
                    const on = user.roles.includes(item);
                    return (
                      <Chip key={item} size="sm" selected={on} disabled={isSelf(user)}
                        onClick={() => void setRoles(user, on ? user.roles.filter((value) => value !== item) : [...user.roles, item])}>
                        {item}
                      </Chip>
                    );
                  })}
                </span>
              ) },
              { key: "status", label: t("ui.status"), render: (user) => <StatusPill status={user.enabled ? "active" : "disabled"} /> },
              { key: "actions", label: t("ui.actions"), render: (user) => {
                if (isSelf(user)) return <span className="fc-muted">—</span>;
                return user.enabled
                  ? <Button size="sm" variant="ghost" icon="userX" onClick={() => setDisabling(user)}>{t("ui.disable")}</Button>
                  : <Button size="sm" icon="userCheck" onClick={() => void setEnabled(user, true)}>{t("ui.enable")}</Button>;
              } },
            ]}
          />
        </>
      ) : (
        <div className="fc-role-grid">
          {roles.map((item) => {
            const sections = allowedSections([item]);
            const readable = (data?.datasets ?? []).filter((dataset) => dataset.readable_roles.includes(item));
            return (
              <section key={item} className="fc-card">
                <div className="fc-card-head">
                  <h2 className="fc-card-title fc-mono">{item}</h2>
                  {packRoles.includes(item) ? <span className="fc-counter" style={{ marginRight: "var(--base-size-8)" }}>{t("ui.members", { n: users.filter((user) => user.roles.includes(item)).length })}</span> : null}
                </div>
                <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
                  <p style={{ margin: 0 }}>{t(`ui.roleDesc_${CONSOLE_ROLES.includes(item) ? item : "analyst"}`)}</p>
                  <dl className="fc-kv fc-kv-stack">
                    <dt>{t("ui.canOpen")}</dt>
                    <dd>
                      <span className="fc-row" style={{ gap: "var(--base-size-4)" }}>
                        {(sections.length ? sections.map((section) => t(`ui.nav_${section.key}`)) : [t("ui.chatApp")]).map((label) => (
                          <span key={label} className="fc-pill fc-pill-neutral">{label}</span>
                        ))}
                      </span>
                    </dd>
                    <dt>{t("ui.dataAccess")}</dt>
                    <dd>
                      {readable.length ? (
                        <span className="fc-row" style={{ gap: "var(--base-size-4)" }}>
                          {readable.map((dataset) => <code key={dataset.id} className="fc-code">{dataset.id}</code>)}
                        </span>
                      ) : <span className="fc-muted">—</span>}
                    </dd>
                  </dl>
                </div>
              </section>
            );
          })}
        </div>
      )}
      <Dialog open={!!disabling} tone="danger" title={t("ui.disableTitle", { name: disabling?.display_name ?? "" })} onClose={() => setDisabling(null)}
        actions={
          <>
            <Button onClick={() => setDisabling(null)}>{t("ui.cancel")}</Button>
            <Button variant="danger" icon="userX" onClick={async () => {
              const user = disabling;
              setDisabling(null);
              if (user) await setEnabled(user, false);
            }}>{t("ui.disable")}</Button>
          </>
        }>
        {t("ui.disableText")}
      </Dialog>
    </ListPage>
  );
}
