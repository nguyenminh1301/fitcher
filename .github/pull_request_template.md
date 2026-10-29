## Summary

<!-- Describe what this PR does and why. Include context a reviewer needs to understand the change. -->

## Type of change

- [ ] New feature
- [ ] Bug fix
- [ ] Refactor (no behavior change)
- [ ] Database migration (new Flyway script)
- [ ] Configuration / infrastructure change
- [ ] Tests only

## Module(s) affected

<!-- List affected module names, e.g. `auth`, `post`, `social` -->

## Author checklist

Complete every item before requesting review.

- [ ] `./mvnw spotless:check` passes (Google AOSP format)
- [ ] `./mvnw test` passes locally

## Database migration checklist

Complete only when this PR includes a Flyway migration script.

- [ ] New migration file follows the naming convention `V{next_number}__{description}.sql`
- [ ] Migration is backward-compatible, or a breaking change is documented in the PR summary
- [ ] `database/schema.sql` is updated to reflect the final state

## Reviewer checklist

- [ ] Code follows the module layer pattern: `controller → service → repository → entity`
- [ ] No cyclic dependencies introduced between modules
- [ ] New endpoints are covered by integration or unit tests

## Related issues

Closes #ISSUE_NUMBER
