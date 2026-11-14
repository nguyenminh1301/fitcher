// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Kind = "postgres" | "mysql";
export type Host = string;
export type Port = number | null;
export type Database = string;
export type SchemaName = string | null;
export type User = string;
export type Password = string;
export type TlsMode = "prefer" | "require" | "verify";
export type CaCertificate = string | null;
export type Name = string;

export interface SourceCreate {
  kind: Kind;
  host: Host;
  port?: Port;
  database: Database;
  schema_name?: SchemaName;
  user: User;
  password: Password;
  tls_mode?: TlsMode;
  ca_certificate?: CaCertificate;
  name: Name;
}
