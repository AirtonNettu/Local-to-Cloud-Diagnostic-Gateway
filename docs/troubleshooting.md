# Troubleshooting

> Language: English · [Português (Brasil)](troubleshooting.pt-BR.md)

## Deploy-time first checks (cannot be verified offline)

These three fail only against a real AWS account, so check them first when a
fresh deployment misbehaves:

1. **KMS AccessDenied on SSM SecureString decryption.** The functions read the
   two keys with `GetParameters(WithDecryption=True)`, which needs KMS decrypt on
   the managed `alias/aws/ssm` key. A `KMS AccessDeniedException` (surfaced as a
   503 from the API) means the key policy or role is missing that decrypt grant.
2. **`sam build` cannot resolve `CodeUri: ../src`.** SAM resolves `CodeUri`
   relative to the template's directory. Run `sam build` from `infrastructure/`
   (or pass `-t infrastructure/template.yaml`) so `../src` points at the package
   root. This is untestable here because the SAM CLI is not installed.
3. **HTTP API access-log permission.** Enabling access logging requires API
   Gateway to create a service-linked role for `ops.apigateway.amazonaws.com`,
   which needs `iam:CreateServiceLinkedRole` for that service principal on the
   deploying identity. Without it the first deploy fails while attaching the
   access-log destination to the stage.

## Agent runtime issues

- **Sync is disabled.** `status` shows sync disabled when `API_BASE_URL` or
  `AGENT_API_KEY` is empty. Set both in `.env`; local commands work regardless.
- **Which `.env` was loaded.** The lookup order is `--env-file PATH` → `./.env`
  → `<data dir>/.env`. `status` prints the chosen path (never the contents), or
  "none". A scheduled `run` starting in a different working directory may pick a
  different file than you expect.
- **401 Unauthorized.** The key is missing or wrong, or has the wrong scope for
  the route (a `read` key on an ingest route is 403). Check `AGENT_API_KEY`.
- **`CONFIG_ERROR` and the cycle aborts.** `API_BASE_URL` points at something
  that redirects or returns an unexpected status. Configure the final HTTPS URL;
  the agent never follows redirects, so the key is never sent to the target.
- **Events stuck PENDING, offline attempts accumulating.** If `API_BASE_URL`
  names a host that does not resolve, every cycle is offline, so events stay
  PENDING with `attempt_count = 0` rather than dead-lettering. `status` shows the
  last attempt as `OFFLINE (…)`. Fix the hostname; sync resumes automatically.
- **`CLOCK_SKEW` warnings.** The agent clock is more than five minutes ahead of
  the server; that event is treated as transient and retried. Fix the local
  clock (enable time sync).
- **Database is locked.** Another process holds the SQLite write lock. The run
  still prints its report and exits 1 with `event=storage_error`; retry once the
  other process releases the lock.
- **"database needs migration" on a read-only command.** Read-only commands
  never migrate. Run a writing command (`scan`) once to apply the migration, or
  the schema is older than this build (`SchemaOutdatedError`).
- **PowerShell blocked by execution policy.** The read-only CIM queries run
  PowerShell; a restrictive policy makes those fields "unavailable" (the run
  continues). Allow the current user to run signed/local scripts if you need GPU,
  gateway/DNS or disk-health data.
- **New device id after deleting the database.** The identity lives in the DB. If
  you delete `agent.db`, a new UUIDv4 identity is generated. Set `DEVICE_ID` in
  `.env` to pin a stable identity across resets.
- **WMI / CIM unavailable.** When the platform queries fail, GPU, gateway/DNS and
  physical-disk sections show "unavailable" and the exit code stays 0; the rest
  of the diagnostics are unaffected.
