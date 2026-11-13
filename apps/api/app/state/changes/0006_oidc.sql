-- OpenID Connect sign-in (DECISIONS §9). oidc_subject is "<issuer> <sub>" of
-- the account created by a provider's first sign-in; a local account has none.
ALTER TABLE accounts ADD COLUMN oidc_subject TEXT;

CREATE UNIQUE INDEX accounts_by_oidc_subject ON accounts (oidc_subject) WHERE oidc_subject IS NOT NULL;

-- Sign-ins sent to the provider and not yet back: the state the callback must
-- return, the PKCE verifier, the nonce the ID token must carry and the
-- redirect URI the code exchange repeats. Seconds since the epoch.
CREATE TABLE oidc_logins
(
    state TEXT PRIMARY KEY,
    verifier TEXT NOT NULL,
    nonce TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at REAL NOT NULL
);
