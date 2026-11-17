# Google bootstrap admin (`manage.py bootstrap`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command (`manage.py bootstrap`) configures a fresh clone: it writes the Google OAuth `SocialApp` row and pre-creates the admin superuser, after which only pre-created accounts can sign in.

**Architecture:** A Django management command runs `migrate --run-syncdb`, upserts the single Google `SocialApp`, and creates/promotes the admin user. A custom social-account adapter closes signup for everyone; the pre-created admin signs in through allauth's email authentication (auto-connect), which matches the user by their verified Google email. The login button reads its client id from the `SocialApp` row instead of a hardcoded value.

**Tech Stack:** Django 6.0, django-allauth 65.13.1, SQLite, Django's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-11-17-google-bootstrap-admin-design.md`

## Global Constraints

- Run every command from `server/` using `../env/bin/python`.
- Tests use Django's runner (`../env/bin/python manage.py test`). There is no pytest.
- Pinned deps: Django 6.0, django-allauth 65.13.1. Do not add dependencies.
- Only Google is configured; `SOCIALACCOUNT_ONLY = True`; `ACCOUNT_EMAIL_VERIFICATION = 'none'`.
- `SOCIALACCOUNT_PROVIDERS["google"]` keeps exactly `AUTH_PARAMS` and `OAUTH_PKCE_ENABLED`.
- No credential may be committed. `local_settings.py` stays gitignored.
- Do not add inline `<script>` to any template: `SECURE_CSP` pins a SHA-256 hash in `settings.py`.
- Commit directly onto `master` (the user's explicit choice).
- A benign `fields.W163` warning (SQLite `db_comment`) appears in test output. Ignore it.

## Review Focus

The spec implies these inputs/conditions but no requirement names them. Each has a test in the task that owns the code.

1. Running `bootstrap` again with **new credentials** must update the one row in place — a second Google `SocialApp` makes allauth raise `MultipleObjectsReturned` on every login. (Task 1)
2. An admin email whose **case differs** from the stored user's must resolve to that user, not create a duplicate. (Task 1)
3. The login page with **no `SocialApp` row** must render (200), not 500. (Task 3)
4. A Google sign-in for an email with **no matching user** must show "sign up is currently closed", not create an account. (Task 2)
5. `bootstrap` with all three values supplied and **stdin not a TTY** must not block on a prompt. (Task 1)

---

### Task 0: Commit the design and plan

**Files:**
- Create (already on disk, untracked): `docs/superpowers/specs/2026-11-17-google-bootstrap-admin-design.md`
- Create (already on disk, untracked): `docs/superpowers/plans/2026-11-17-google-bootstrap-admin.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing (documentation only).

- [ ] **Step 1: Confirm only the docs are untracked**

Run: `git status --short`
Expected: `?? docs/` and nothing else.

- [ ] **Step 2: Commit**

```bash
git add docs
git commit -m "docs: design and plan for manage.py bootstrap"
```

---

### Task 1: The `manage.py bootstrap` command

**Files:**
- Create: `server/webapp/management/__init__.py` (empty)
- Create: `server/webapp/management/commands/__init__.py` (empty)
- Create: `server/webapp/management/commands/bootstrap.py`
- Test: `server/webapp/tests.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `upsert_google_app(client_id: str, secret: str) -> SocialApp`
  - `ensure_admin_user(email: str) -> tuple[User, bool]` (the bool is `created`)
  - `_stdin_is_tty() -> bool` (module-level; patched by tests)
  - `Command` with flags `--client-id`, `--client-secret`, `--admin-email`, `--noinput`

- [ ] **Step 1: Create the management packages**

```bash
mkdir -p server/webapp/management/commands
touch server/webapp/management/__init__.py server/webapp/management/commands/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `server/webapp/tests.py`:

```python
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase

from allauth.socialaccount.models import SocialApp

from .management.commands.bootstrap import ensure_admin_user, upsert_google_app


class UpsertGoogleAppTests(TestCase):
    def test_creates_the_single_app_when_none_exists(self):
        app = upsert_google_app("cid", "secret")
        self.assertEqual(SocialApp.objects.count(), 1)
        self.assertEqual(app.provider, "google")
        self.assertEqual(app.client_id, "cid")
        self.assertEqual(app.secret, "secret")

    def test_updates_in_place_and_deletes_duplicates(self):
        first = SocialApp.objects.create(
            provider="google", name="Old", client_id="old", secret="old"
        )
        SocialApp.objects.create(
            provider="google", name="Dup", client_id="dup", secret="dup"
        )
        app = upsert_google_app("new", "new-secret")
        self.assertEqual(SocialApp.objects.count(), 1)
        self.assertEqual(app.pk, first.pk)
        self.assertEqual(app.client_id, "new")
        self.assertEqual(app.secret, "new-secret")


class EnsureAdminUserTests(TestCase):
    def test_creates_staff_superuser_with_unusable_password(self):
        user, created = ensure_admin_user("admin@example.com")
        self.assertTrue(created)
        self.assertEqual(user.username, "admin@example.com")
        self.assertEqual(user.email, "admin@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.has_usable_password())

    def test_promotes_an_existing_user_and_keeps_its_username(self):
        existing = get_user_model().objects.create_user(
            "oleksandr", email="admin@example.com"
        )
        user, created = ensure_admin_user("admin@example.com")
        self.assertFalse(created)
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.username, "oleksandr")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_matches_an_existing_user_case_insensitively(self):
        existing = get_user_model().objects.create_user(
            "oleksandr", email="admin@example.com"
        )
        user, created = ensure_admin_user("Admin@Example.com")
        self.assertFalse(created)
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_is_idempotent(self):
        first, _ = ensure_admin_user("admin@example.com")
        second, created = ensure_admin_user("admin@example.com")
        self.assertFalse(created)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(get_user_model().objects.count(), 1)


class BootstrapCommandTests(TransactionTestCase):
    # TransactionTestCase, not TestCase: the command calls `migrate`, which
    # SQLite refuses inside a TestCase's atomic block.

    def test_run_writes_the_app_and_the_admin(self):
        call_command(
            "bootstrap",
            client_id="cid",
            client_secret="secret",
            admin_email="admin@example.com",
            verbosity=0,
        )
        self.assertEqual(SocialApp.objects.get().client_id, "cid")
        user = get_user_model().objects.get(email="admin@example.com")
        self.assertTrue(user.is_superuser)

    def test_run_is_idempotent(self):
        for _ in range(2):
            call_command(
                "bootstrap",
                client_id="cid",
                client_secret="secret",
                admin_email="admin@example.com",
                verbosity=0,
            )
        self.assertEqual(SocialApp.objects.count(), 1)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_missing_values_with_noinput_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("bootstrap", noinput=True, verbosity=0)


class BootstrapPromptTests(TestCase):
    def test_prompts_for_missing_values_when_interactive(self):
        with mock.patch(
            "webapp.management.commands.bootstrap._stdin_is_tty",
            return_value=True,
        ), mock.patch(
            "builtins.input", side_effect=["cid", "admin@example.com"]
        ), mock.patch(
            "getpass.getpass", return_value="secret"
        ), mock.patch(
            "webapp.management.commands.bootstrap.call_command"
        ) as migrate:
            call_command("bootstrap", verbosity=0)
        migrate.assert_called_once()
        self.assertEqual(migrate.call_args.args[0], "migrate")
        self.assertTrue(migrate.call_args.kwargs["run_syncdb"])
        self.assertEqual(SocialApp.objects.get().client_id, "cid")
        self.assertTrue(
            get_user_model().objects.get(email="admin@example.com").is_superuser
        )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `../env/bin/python manage.py test webapp`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'webapp.management.commands.bootstrap'`.

- [ ] **Step 4: Implement `server/webapp/management/commands/bootstrap.py`**

```python
"""One-shot setup for a fresh install.

Writes the Google OAuth credentials into the database and pre-creates the admin
superuser, so a clone can be bootstrapped without shell access to the DB.
"""

import getpass
import sys

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from allauth.socialaccount.models import SocialApp


def upsert_google_app(client_id: str, secret: str) -> SocialApp:
    """Create or update the single Google SocialApp, deleting any duplicates.

    Two Google apps make allauth raise MultipleObjectsReturned on every login,
    so this guarantees exactly one row remains.
    """
    apps = list(SocialApp.objects.filter(provider="google").order_by("pk"))
    app = apps[0] if apps else SocialApp(provider="google")
    for duplicate in apps[1:]:
        duplicate.delete()
    app.name = "Google"
    app.client_id = client_id
    app.secret = secret
    app.save()
    return app


def ensure_admin_user(email: str):
    """Create the admin user, or promote the one whose email matches.

    Returns (user, created). A new user gets the email as its username and no
    usable password (it signs in through Google). An existing user keeps its
    username and password.
    """
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    created = user is None
    if created:
        user = User(username=email, email=email)
        user.set_unusable_password()
    user.is_staff = True
    user.is_superuser = True
    user.save()
    return user, created


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


class Command(BaseCommand):
    help = "Configure Google sign-in and create the admin superuser."

    def add_arguments(self, parser):
        parser.add_argument("--client-id", help="Google OAuth client ID.")
        parser.add_argument("--client-secret", help="Google OAuth client secret.")
        parser.add_argument("--admin-email", help="Google email of the admin user.")
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="Never prompt; fail if a value is missing.",
        )

    def handle(self, *args, **options):
        client_id = self._resolve(
            options["client_id"], "Google client ID", "--client-id", options
        )
        client_secret = self._resolve(
            options["client_secret"],
            "Google client secret",
            "--client-secret",
            options,
            secret=True,
        )
        admin_email = self._resolve(
            options["admin_email"], "admin email", "--admin-email", options
        )

        call_command("migrate", run_syncdb=True, verbosity=options["verbosity"])

        app = upsert_google_app(client_id, client_secret)
        user, created = ensure_admin_user(admin_email)

        self.stdout.write(f"Google sign-in app #{app.pk} is configured.")
        self.stdout.write(f"{'Created' if created else 'Promoted'} admin {user.email}.")
        self.stdout.write(
            "Next: run `manage.py runserver` and sign in with that Google account."
        )

    def _resolve(self, value, label, flag, options, secret=False) -> str:
        if value:
            return value.strip()
        if options["noinput"] or not _stdin_is_tty():
            raise CommandError(f"Missing {label}: pass {flag} or run interactively.")
        if secret:
            return getpass.getpass(f"{label}: ").strip()
        return input(f"{label}: ").strip()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `../env/bin/python manage.py test webapp`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add server/webapp/management server/webapp/tests.py
git commit -m "feat: add manage.py bootstrap to configure Google sign-in and the admin"
```

---

### Task 2: Close signup for everyone; delete the first-user promotion

**Files:**
- Create: `server/webapp/adapters.py`
- Modify: `server/webapp/settings.py` (add three settings after `SOCIALACCOUNT_ONLY`)
- Modify: `server/webapp/apps.py` (remove the `ready()` method)
- Delete: `server/webapp/signals.py`
- Test: `server/webapp/tests.py` (append)

**Interfaces:**
- Consumes: `ensure_admin_user` from Task 1.
- Produces: `BootstrapSocialAccountAdapter` at import path `webapp.adapters.BootstrapSocialAccountAdapter`.

- [ ] **Step 1: Append the failing tests**

Add these imports to the top of `server/webapp/tests.py`:

```python
from django.conf import settings
from django.urls import reverse

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin
from allauth.socialaccount.providers import registry

from .adapters import BootstrapSocialAccountAdapter
```

Append these classes:

```python
class SignupClosedTests(TestCase):
    def test_adapter_closes_signup_for_everyone(self):
        self.assertFalse(
            BootstrapSocialAccountAdapter().is_open_for_signup(None, None)
        )

    def test_adapter_and_email_authentication_are_configured(self):
        self.assertEqual(
            settings.SOCIALACCOUNT_ADAPTER,
            "webapp.adapters.BootstrapSocialAccountAdapter",
        )
        self.assertTrue(settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION)
        self.assertTrue(settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT)

    def _social_login(self, email):
        app = SocialApp.objects.create(
            provider="google", name="Google", client_id="cid", secret="s"
        )
        provider = registry.get_class("google")(request=None, app=app)
        return SocialLogin(
            provider=provider,
            user=get_user_model()(email=email),
            account=SocialAccount(provider="google", uid="123"),
            email_addresses=[EmailAddress(email=email, verified=True)],
        )

    def test_signup_view_is_closed_for_an_unknown_google_email(self):
        session = self.client.session
        session["socialaccount_sociallogin"] = self._social_login(
            "stranger@example.com"
        ).serialize()
        session.save()
        response = self.client.get(reverse("socialaccount_signup"))
        self.assertContains(response, "sign up is currently closed")

    def test_email_authentication_resolves_the_pre_created_admin(self):
        user, _ = ensure_admin_user("admin@example.com")
        sociallogin = self._social_login("admin@example.com")
        sociallogin.lookup()
        self.assertEqual(sociallogin.user.pk, user.pk)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../env/bin/python manage.py test webapp.tests.SignupClosedTests`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'webapp.adapters'` (and the email-auth test fails because `SOCIALACCOUNT_EMAIL_AUTHENTICATION` is not set yet).

- [ ] **Step 3: Create `server/webapp/adapters.py`**

```python
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class BootstrapSocialAccountAdapter(DefaultSocialAccountAdapter):
    """No account may create itself.

    Accounts are pre-created by `manage.py bootstrap` (or later by the admin).
    The admin signs in through allauth's email authentication, which resolves
    the pre-created user before this hook is ever consulted.
    """

    def is_open_for_signup(self, request, sociallogin) -> bool:
        return False
```

- [ ] **Step 4: Add the settings**

In `server/webapp/settings.py`, immediately after the `SOCIALACCOUNT_PROVIDERS` block (after line 155), add:

```python
SOCIALACCOUNT_ADAPTER = 'webapp.adapters.BootstrapSocialAccountAdapter'
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
```

- [ ] **Step 5: Delete `signals.py` and its wiring**

Delete the file:

```bash
git rm server/webapp/signals.py
```

In `server/webapp/apps.py`, remove the `ready()` method so the file is exactly:

```python
from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'webapp'
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `../env/bin/python manage.py test webapp`
Expected: PASS (14 tests).

- [ ] **Step 7: Confirm nothing still references `signals`**

Run: `grep -rn --include='*.py' --include='*.html' "signals" server/webapp server/templates || echo "no references"`
Expected: `no references`.

- [ ] **Step 8: Commit**

```bash
git add server/webapp/adapters.py server/webapp/settings.py server/webapp/apps.py server/webapp/tests.py
git commit -m "feat: close signup and drop the first-user promotion"
```

---

### Task 3: The login button reads its client id from the `SocialApp` row

**Files:**
- Create: `server/templates/socialaccount/snippets/provider_list.html`
- Modify: `server/templates/allauth/elements/provider.html:3`
- Test: `server/webapp/tests.py` (append)

**Interfaces:**
- Consumes: a `SocialApp` row (created by `bootstrap` in Task 1; tests create their own).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Append the failing tests**

Add this import to the top of `server/webapp/tests.py`:

```python
from django.template.loader import render_to_string
```

Append:

```python
class LoginButtonTests(TestCase):
    def test_provider_element_renders_the_client_id_it_is_given(self):
        html = render_to_string(
            "allauth/elements/provider.html",
            {"attrs": {"provider_id": "google", "client_id": "client-from-attrs"}},
        )
        self.assertIn('data-client_id="client-from-attrs"', html)

    def test_login_page_uses_the_client_id_from_the_social_app(self):
        SocialApp.objects.create(
            provider="google",
            name="Google",
            client_id="client-from-db.apps.googleusercontent.com",
            secret="s",
        )
        response = self.client.get(reverse("account_login"))
        self.assertContains(
            response, 'data-client_id="client-from-db.apps.googleusercontent.com"'
        )

    def test_login_page_renders_without_a_social_app(self):
        response = self.client.get(reverse("account_login"))
        self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `../env/bin/python manage.py test webapp.tests.LoginButtonTests`
Expected: FAIL on the first two tests — the element still renders the hardcoded id `956920296212-...`.

- [ ] **Step 3: Override the provider-list snippet**

Create `server/templates/socialaccount/snippets/provider_list.html` (allauth's snippet plus `client_id=provider.app.client_id` on both element calls):

```html
{% load allauth socialaccount %}
{% get_providers as socialaccount_providers %}
{% if socialaccount_providers %}
    {% element provider_list %}
        {% for provider in socialaccount_providers %}
            {% if provider.id == "openid" %}
                {% for brand in provider.get_brands %}
                    {% provider_login_url provider openid=brand.openid_url process=process as href %}
                    {% element provider name=brand.name provider_id=provider.id href=href client_id=provider.app.client_id %}
                    {% endelement %}
                {% endfor %}
            {% endif %}
            {% provider_login_url provider process=process scope=scope auth_params=auth_params as href %}
            {% element provider name=provider.name provider_id=provider.id href=href client_id=provider.app.client_id %}
            {% endelement %}
        {% endfor %}
    {% endelement %}
{% endif %}
```

- [ ] **Step 4: Render the client id in the provider element**

In `server/templates/allauth/elements/provider.html`, change line 3 from the hardcoded id to:

```html
     data-client_id="{{ attrs.client_id }}"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `../env/bin/python manage.py test webapp`
Expected: PASS (17 tests).

- [ ] **Step 6: Commit**

```bash
git add server/templates/socialaccount/snippets/provider_list.html server/templates/allauth/elements/provider.html server/webapp/tests.py
git commit -m "feat: read the Google client id from the SocialApp row"
```

---

### Task 4: Document the bootstrap flow

**Files:**
- Create: `README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: the command and behaviour from Tasks 1-3.
- Produces: nothing.

- [ ] **Step 1: Write `README.md`**

````markdown
# Boilermote

A Django app that reads a MAX6675 thermocouple over SPI (Raspberry Pi) and shows
temperature readings. Sign-in is Google-only.

## Requirements

- Python 3.12+
- A Raspberry Pi with the sensor wired up, if you want real readings. The web
  app and its tests run fine without one.

## Setup

From the repository root:

```bash
python3 -m venv env
env/bin/pip install -r requirements.txt
cd server
../env/bin/python manage.py bootstrap
../env/bin/python manage.py runserver
```

`manage.py bootstrap` is the only setup step. It will:

1. Ask for your Google OAuth **client ID** and **client secret** (create an
   OAuth client of type "Web application" in the Google Cloud console) and for
   the **email** of the account that should be the admin.
2. Run the database migrations.
3. Save the client ID and secret in the database.
4. Create (or promote) the admin user.

Then open the server and sign in with that Google account.

You can pass the values as flags instead of being prompted — useful on a machine
with no terminal:

```bash
../env/bin/python manage.py bootstrap \
    --client-id "....apps.googleusercontent.com" \
    --client-secret "..." \
    --admin-email "you@example.com"
```

Re-running `bootstrap` is safe: it updates the same Google app and the same
admin user.

## Who can sign in

Only accounts that already exist can sign in. `bootstrap` creates the first
one (the admin); there is no self-signup. Any other Google account sees
allauth's "Sign up closed" page.

## Tests

```bash
cd server
../env/bin/python manage.py test
```
````

- [ ] **Step 2: Update `AGENTS.md`**

Make these edits:

1. In `## Layout`, replace `apps: \`webapp\` (project config, allauth signals)` with `apps: \`webapp\` (project config, allauth adapter)`.
2. In the `## Commands` code block, add this line before `../env/bin/python manage.py migrate`:

   ```bash
   ../env/bin/python manage.py bootstrap   # first-time Google + admin setup
   ```

3. In `## Server specifics`, replace this bullet:

   > `SOCIALACCOUNT_ONLY=True`, email verification off; Google is the only sign-in provider. OAuth client ID/secret are stored as a `SocialApp` row in the DB (configure via admin), not in settings.

   with:

   > `SOCIALACCOUNT_ONLY=True`, email verification off; Google is the only sign-in provider. The OAuth client ID/secret live in a single `SocialApp` row, written by `manage.py bootstrap` (there is no `local_settings.py` and no settings-backed app). The login button reads its client id from that row.

4. In `## Server specifics`, replace this bullet:

   > `webapp/signals.py` auto-promotes the **first** user to sign up to staff/superuser (wired via `WebappConfig.ready()`). Don't add a second automatic-admin path.

   with:

   > `webapp/adapters.py` (`BootstrapSocialAccountAdapter`) closes signup for everyone; accounts are pre-created by `manage.py bootstrap`. `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and `..._AUTO_CONNECT` let the pre-created admin sign in with their verified Google email.

5. Add this new section immediately after the `## Commands` section:

   ```markdown
   ## Bootstrap (new device)
   ```bash
   cd server
   ../env/bin/python manage.py bootstrap
   ```
   Prompts for the Google client ID/secret and the admin email, runs migrations,
   writes the `SocialApp` row, and creates the admin superuser. Re-runnable.
   Flags `--client-id/--client-secret/--admin-email` (plus `--noinput`) skip the
   prompts. Only pre-created accounts can sign in.
   ```

- [ ] **Step 3: Verify the docs match the code**

Run: `grep -n "manage.py bootstrap" README.md AGENTS.md`
Expected: both files match.

Run: `grep -n "signals.py\|local_settings" AGENTS.md || echo "stale references gone"`
Expected: `stale references gone`.

- [ ] **Step 4: Run the full suite once more**

Run: `../env/bin/python manage.py test`
Expected: PASS (all `webapp` and `boiler` tests).

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: add README and update AGENTS.md for manage.py bootstrap"
```

---

## After the plan

Two things the implementer cannot do from here and must hand back:

1. **Manual browser check (owner's).** With real Google credentials and a real
   browser, run `bootstrap`, then sign in once with the admin Google account and
   once with a different Google account, confirming the admin lands logged in and
   the stranger sees "Sign up closed".
2. **Delete the now-unused `server/webapp/local_settings.py`.** It holds the
   owner's real credentials and is dead once `bootstrap` has run. Its three
   values are the inputs to `bootstrap`. Confirm with the owner before deleting.
