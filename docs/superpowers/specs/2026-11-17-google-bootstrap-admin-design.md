# Design: Google bootstrap via `manage.py bootstrap`

Date: 2026-11-17
Size: small change
Revision: 2 (supersedes the rev-1 "local_settings.py" design)

## Intent

On a freshly cloned device, the app should be bootstrappable without shell access
to the database and without hand-editing config files. Run one command, supply the
Google OAuth credentials and your admin email, start the server, sign in with that
Google account, and you are the superuser. No other Google account can get in.

Today this is impossible: the credentials live in a `SocialApp` DB row, adding that
row requires logging into `/admin/`, and logging into `/admin/` requires an account,
which can only be created by signing in with Google.

## Why this replaces rev 1

Rev 1 put the three values in a gitignored `server/webapp/local_settings.py` and
gated signup on the admin email. It was never shipped — the commits were reverted
before this revision — but three problems surfaced while building it:

1. **The config file was not actually authoritative.** The login button hardcoded a
   client id in `server/templates/allauth/elements/provider.html:3`. allauth verifies
   the returned token against the app's `client_id`, so supplying a *different* id in
   the config file produced a button that silently failed.
2. **The admin email had no good home.** Client id/secret belong in a `SocialApp`
   row, but the app must know the admin email *before* the first sign-in, so it needed
   a second, separate storage mechanism for one string.
3. **It kept two notions of "the app"** — a settings-backed one and a DB-backed one —
   which collide (`MultipleObjectsReturned`) and required a manual deletion step.

Rev 2 puts everything in the DB, driven by a management command, and removes the
admin email from runtime entirely by creating the admin user up front.

## Goals

- A fresh clone bootstraps with one command: `manage.py bootstrap` collects the
  client id, client secret and admin email, runs migrations, writes the `SocialApp`
  row, and creates the admin user.
- Signing in with that Google account lands on the superuser. No other account can
  sign in or sign up.
- The command is re-runnable and idempotent.
- No config file, no environment variable, no secret in the repo.

## Non-goals

- Inviting or adding further users. (Out of scope, as before.)
- Production hardening: `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS` stay as they are.
- Adding a migrations package to the `boiler` app.

## Anti-goals

- A stranger's Google account ever becoming superuser.
- Credentials committed to the repo.
- The app 500-ing because config is missing.

## Constraints (verified against Django 6.0 / django-allauth 65.13.1)

- `SOCIALACCOUNT_ONLY = True`, so allauth does not register `account_signup`;
  there is no signup UI. `SOCIALACCOUNT_AUTO_SIGNUP` defaults to True, so an unknown
  Google account is silently auto-created — that is the de-facto signup path, and it
  must be closed.
- allauth calls `is_open_for_signup(request, sociallogin)` immediately before creating
  a social user; returning False renders its built-in `account/signup_closed.html`.
  Already-linked accounts take the `sociallogin.is_existing` path and never reach it.
- `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and `..._AUTO_CONNECT` both default to False.
- `SocialLogin.lookup()` falls back to a **`User.email` query** when no `EmailAddress`
  row matches (`account/utils.py:272-278`, `USER_MODEL_EMAIL_FIELD` defaults to
  `"email"`), and only skips that fallback when a *verified* `EmailAddress` exists. So
  a user created with no `EmailAddress` row is still found.
- Google returns `email_verified`, and its provider marks the address verified.
- `can_authenticate_by_email` returns True once `EMAIL_AUTHENTICATION` is on.
- `wipe_password` only acts on accounts with a *usable* password and an unverified
  address; an unusable-password user is untouched.
- `list_apps()` builds an **unsaved** `SocialApp` from `SOCIALACCOUNT_PROVIDERS` on
  every call; nothing is ever written to the DB from settings.
- `list_providers()` sets `provider.app` to the `SocialApp`, so a template can read
  `client_id` from it.
- The hashed inline script in the CSP config is the theme toggle in
  `server/templates/allauth/layouts/base.html`, not the client id. Changing the
  button's client id does not invalidate the hash.
- `SocialAccount` has no FK to `SocialApp`; `SocialToken.app` exists but
  `STORE_TOKENS` defaults to False.
- The `boiler` app has no migrations directory, so `migrate` alone never creates
  `boiler_temperaturereading`; `migrate --run-syncdb` does.

## Approaches considered

- **A. Keep the admin email in the DB** (small edit to rev 1: a one-row model the gate
  reads). Rejected: still a second home for one string, and a model plus migration
  just to hold it.
- **B. `bootstrap` creates the admin user up front; no email at runtime (chosen).**
  The user table becomes the source of truth, so there is nothing to store. Signup
  closes for everyone, and the pre-created user signs in through allauth's email
  authentication, which auto-connects their social account. Deletes more code than it
  adds: the `BOOTSTRAP_ADMIN_EMAIL` setting, the adapter's email-matching logic and the
  `user_signed_up` promotion all disappear.
- **C. Truly ephemeral (in-memory) email.** Rejected: `manage.py bootstrap` and
  `manage.py runserver` are separate processes, so nothing set in memory survives; it
  would force re-running bootstrap after every restart.

## Design

### 1. `manage.py bootstrap`

`server/webapp/management/commands/bootstrap.py`.

Inputs, all optional as flags: `--client-id`, `--client-secret`, `--admin-email`.
Any value not supplied as a flag is prompted for; the secret is read with `getpass`
so it is not echoed. If a value is still missing when input is unavailable
(`--noinput`, or stdin not a TTY), the command fails with a clear `CommandError`
rather than half-configuring the install.

Steps, in order:

1. `call_command("migrate", run_syncdb=True)` — the `boiler` app has no migrations, so
   plain `migrate` would leave its table missing.
2. Create or update the single `SocialApp` for provider `google` (name `Google`).
   Never leave two, because allauth raises `MultipleObjectsReturned` on two.
3. Create the admin user if it does not exist, and ensure `is_staff` and
   `is_superuser` either way. No password: the account is only reachable through
   Google. A *new* user gets the email as its username (Django needs a unique one);
   an existing user found by email keeps its current username.
4. Print a short summary: what was created, what was updated, and the next step
   (`manage.py runserver`, then sign in with that Google account).

The command is idempotent: running it again updates the same row and the same user.
It never prints the secret back.

### 2. Settings

The base `settings.py` has no `local_settings` import and no `APP` key (rev 1 was
reverted before shipping), so nothing is removed here — the credentials simply stay
out of settings from now on. `SOCIALACCOUNT_PROVIDERS["google"]` keeps `AUTH_PARAMS`
and `OAUTH_PKCE_ENABLED` only. Add:

```python
SOCIALACCOUNT_ADAPTER = "webapp.adapters.BootstrapSocialAccountAdapter"
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
```

### 3. Adapter

`server/webapp/adapters.py` is a **new** file (the base has no adapter) that closes
signup for everyone:

```python
class BootstrapSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return False
```

Every account is pre-created by `bootstrap` (or later by the admin), so nothing may
sign itself up. No email matching, no `BOOTSTRAP_ADMIN_EMAIL`.

### 4. Delete `signals.py` and its wiring

Promotion is unnecessary: `bootstrap` creates the superuser. Delete
`server/webapp/signals.py` and the `from . import signals` import in
`server/webapp/apps.py`.

### 5. The login button reads its client id from the app

Override `server/templates/socialaccount/snippets/provider_list.html` (a copy of
allauth's, ~12 lines) so the `{% element provider %}` call passes
`client_id=provider.app.client_id`, and change
`server/templates/allauth/elements/provider.html:3` to render
`data-client_id="{{ attrs.client_id }}"`.

This makes the DB the single home for the client id, which is the point of rev 2.

### 6. Documentation

- New root `README.md`: what the app is, how to set up a fresh clone (venv,
  `pip install -r requirements.txt`, `manage.py bootstrap`, `manage.py runserver`),
  what `bootstrap` asks for and does, and the rule that only pre-created accounts can
  sign in.
- `AGENTS.md`: add a `## Bootstrap` section describing `manage.py bootstrap`, and
  replace the `signals.py` "auto-promotes the first user" line, since that file is
  deleted.

### 7. Tests

`server/webapp/tests.py` is a **new** file (the base `webapp` app has no tests):

- `bootstrap` writes a `SocialApp` with the supplied client id and secret.
- `bootstrap` creates the admin user as staff + superuser with an unusable password.
- `bootstrap` is idempotent: a second run leaves one app and one user, and updates
  the row when values change.
- `bootstrap` fails cleanly when a value is missing and input is unavailable.
- `is_open_for_signup` is False for any email, so no account can self-create.
- The email-authentication mechanism that rev 2 depends on: given the pre-created
  user and a *verified* Google email with no matching `SocialAccount`,
  `SocialLogin.lookup()` resolves to that user.
- The login page renders the client id from the `SocialApp` row.
- The two `SOCIALACCOUNT_EMAIL_AUTHENTICATION*` settings are on.

### 8. Removals

- `server/webapp/signals.py` — the base file promotes the *first* user to sign up to
  superuser. Superseded: `bootstrap` creates the admin, and letting any first signup
  self-promote would defeat the gate.
- The `from . import signals` line in `server/webapp/apps.py`.
- The local, gitignored `server/webapp/local_settings.py` the user created while trying
  rev 1. Its three values are exactly the inputs to `bootstrap`, so it is read for those
  and then dead. (Confirm before deleting — it holds the real credentials.)

*My call:* leave the `local_settings.py` line in `.gitignore`. It is a common Django
convention and costs nothing; removing it is optional.

## Known edge cases (accepted)

- **Nothing configured.** With no `SocialApp` row, allauth lists no Google provider, so
  the login page renders empty rather than 500-ing. `README.md` points at `bootstrap`.
- **The admin's email changes.** The Google email no longer matches any user, so signup
  is closed and they are locked out until the email is corrected in `/admin/`.
- **Trust caveat of `EMAIL_AUTHENTICATION`.** It lets a verified provider email claim an
  existing local account. Google is the only provider and there are no password
  accounts, so this is the intended use; the risk returns only if a password login is
  added later.
- **Deleting the admin's social account** does not lock them out: the email still
  matches the user, so the next Google sign-in auto-connects a fresh one.

## Left to the builder

- Exact prompt and summary wording.
- Whether `bootstrap` should also create an `EmailAddress` row (not needed — the
  `User.email` fallback finds the user — but harmless).
- The `README.md` structure and how much of the temperature/`boiler` side to cover.
