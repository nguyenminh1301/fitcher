// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

/**
 * @minItems 1
 */
export type AllowedRoles = [string, ...string[]];

export interface DocumentRolesChange {
  allowed_roles: AllowedRoles;
}
