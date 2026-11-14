// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Host = string | null;
export type Port = number | null;
export type Database = string | null;
export type SchemaName = string | null;
export type User = string | null;
export type Password = string | null;
export type TlsMode = ("prefer" | "require" | "verify") | null;
export type CaCertificate = string | null;

export interface SourcePatch {
  host?: Host;
  port?: Port;
  database?: Database;
  schema_name?: SchemaName;
  user?: User;
  password?: Password;
  tls_mode?: TlsMode;
  ca_certificate?: CaCertificate;
}
