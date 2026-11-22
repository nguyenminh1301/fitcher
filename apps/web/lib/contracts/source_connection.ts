// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Kind = "postgres" | "mysql" | "sqlserver";
export type Host = string;
export type Port = number | null;
export type Database = string;
export type SchemaName = string | null;
export type User = string;
export type Password = string;
export type TlsMode = ("prefer" | "require" | "verify") | null;
export type CaCertificate = string | null;

/**
 * The connection fields of a PostgreSQL or MySQL/MariaDB source.
 */
export interface SourceConnection {
  kind: Kind;
  host: Host;
  port?: Port;
  database: Database;
  schema_name?: SchemaName;
  user: User;
  password: Password;
  tls_mode?: TlsMode;
  ca_certificate?: CaCertificate;
}
