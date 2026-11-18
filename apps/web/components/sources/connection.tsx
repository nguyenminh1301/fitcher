"use client";

// What a database connection is made of, shared by the setup's Data step and the Sources page: the form values,
// the request body built from them, and one fixed message for a failure, never the database's own text. The
// password is sent once to the api, which writes it into ClickHouse; it is never shown again.

import { errorText } from "@/lib/api/errorText";
import { SourceError } from "@/lib/api/http/sources";
import type { SourceConnection } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Kind = SourceConnection["kind"];
type Tls = NonNullable<SourceConnection["tls_mode"]>;
export const KINDS: Kind[] = ["postgres", "mysql", "sqlserver"];
export const TLS: Tls[] = ["prefer", "require", "verify"];
export const DEFAULT_PORTS: Record<Kind, string> = { postgres: "5432", mysql: "3306", sqlserver: "1433" };
export const DEFAULT_SCHEMAS: Partial<Record<Kind, string>> = { postgres: "public", sqlserver: "dbo" };

/** One fixed message for a failure: the api's reason when it gave one, else its own message. */
export function useFailure() {
  const { t } = useI18n();
  return (cause: unknown): string => {
    if (cause instanceof SourceError && cause.reason) return t(`sources.reason_${cause.reason}`);
    if (cause instanceof SourceError && cause.marts?.length) return t("sources.inUse", { marts: cause.marts.join(", ") });
    return t("sources.failed", { reason: errorText(cause) });
  };
}

export type ConnectionValues = {
  kind: Kind; name: string; host: string; port: string; database: string; schema_name: string; user: string;
  password: string; tls_mode: Tls; ca_certificate: string;
};

export const EMPTY_CONNECTION: ConnectionValues = {
  kind: "postgres", name: "", host: "", port: "", database: "", schema_name: "", user: "", password: "", tls_mode: "prefer", ca_certificate: "",
};

/** The request body for a test or a create; an empty port or schema is left out so the api's defaults apply. */
export function connectionBody(values: ConnectionValues): SourceConnection {
  const body: SourceConnection = {
    kind: values.kind, host: values.host.trim(), database: values.database.trim(), user: values.user.trim(),
    password: values.password, tls_mode: values.tls_mode,
  };
  if (values.port) body.port = Number(values.port);
  if (DEFAULT_SCHEMAS[values.kind] && values.schema_name) body.schema_name = values.schema_name.trim();
  if (values.kind !== "sqlserver" && values.ca_certificate.trim()) body.ca_certificate = values.ca_certificate;
  return body;
}

