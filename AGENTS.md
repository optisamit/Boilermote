# AGENTS.md

## Layout
Single Django project in `server/`. `DJANGO_SETTINGS_MODULE=webapp.settings`. Apps: `webapp` (project config, allauth adapter) and `boiler` (temperature model, views). Run all commands from `server/`.

## Environment
- Use `env/bin/python` (from `server/`: `../env/bin/python`). `.venv/` exists but has no packages installed; `env/` has Django 6.0 and django-allauth.
- Dependencies pinned in root `requirements.txt`. Install into `env/` with `env/bin/pip install -r requirements.txt`.
- No pytest, tox, linter, pre-commit, or CI config. Tests use Django's built-in runner.

## Commands (run from inside `server/`)
```bash
cd server
../env/bin/python manage.py test                                      # all boiler tests
../env/bin/python manage.py test boiler                               # single app
../env/bin/python manage.py test boiler.tests.TemperatureReadingTests.test_real_temperature_negative  # single test
../env/bin/python manage.py bootstrap   # first-time Google + admin setup
../env/bin/python manage.py migrate
../env/bin/python manage.py runserver
```

## Bootstrap (new device)
```bash
cd server
../env/bin/python manage.py bootstrap
```
Prompts for the Google client ID/secret and the admin email, runs migrations,
writes the `SocialApp` row, and creates the admin superuser. Re-runnable.
Flags `--client-id/--client-secret/--admin-email` (plus `--noinput`) skip the
prompts. Only pre-created accounts can sign in.

## Server specifics (non-obvious)
- `LoginRequiredMiddleware` is enabled globally, so every view requires login; allauth routes live under `/accounts/` and `LOGIN_REDIRECT_URL='/boiler/'`.
- `SOCIALACCOUNT_ONLY=True`, email verification off; Google is the only sign-in provider. The OAuth client ID/secret live in a single `SocialApp` row, written by `manage.py bootstrap` (there is no `local_settings.py` and no settings-backed app). The login button reads its client id from that row.
- `webapp/adapters.py` (`BootstrapSocialAccountAdapter`) closes signup for everyone; accounts are pre-created by `manage.py bootstrap`. `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and `..._AUTO_CONNECT` let the pre-created admin sign in with their verified Google email.
- CSP is enforced by `SECURE_CSP` + `django.middleware.csp.ContentSecurityPolicyMiddleware`. The Google sign-in hash and `cdn.jsdelivr.net` are allowlisted; changing the inline script in `templates/account/login.html` likely requires updating the SHA-256 hash in `settings.py`.
- `TemperatureReading.temperature` stores °C **doubled as an integer**; use `real_temperature()` to get the actual value.
- `server/m6675.py` is a MAX6675 SPI thermocouple driver (gpiozero/spidev/lgpio); it is hardware-dependent and not usable on a non-Pi machine.
- Project-level `server/templates/` overrides allauth templates (`account/login.html`, `allauth/...`).
- `db.sqlite3` is gitignored. Settings are dev-only: `DEBUG=True`, hardcoded `SECRET_KEY`, empty `ALLOWED_HOSTS`.
