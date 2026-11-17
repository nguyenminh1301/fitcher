-- fitcher is a personal app (DECISIONS §9): the accounts, sessions, sign-in
-- throttle and OpenID Connect sign-in of team mode are removed together with
-- their settings and secret. On an instance that was in team mode, the first
-- admin was created with the owner's id, so the admin's conversations stay the
-- owner's; other accounts' conversations stay in ClickHouse but no longer show.
DROP TABLE IF EXISTS oidc_logins;
DROP TABLE IF EXISTS account_sessions;
DROP TABLE IF EXISTS account_roles;
DROP TABLE IF EXISTS sign_in_failures;
DROP INDEX IF EXISTS accounts_by_oidc_subject;
DROP TABLE IF EXISTS accounts;
DELETE FROM settings WHERE group_name = 'instance' AND key = 'mode';
DELETE FROM settings WHERE group_name = 'oidc';
DELETE FROM secrets WHERE name = 'oidc:client_secret';
DELETE FROM setup_steps WHERE id = 'mode';
