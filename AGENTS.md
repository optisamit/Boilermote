# AGENTS.md

## Layout
Single Django project in `server/`. `DJANGO_SETTINGS_MODULE=webapp.settings`. Apps: `webapp` (project config, allauth signals) and `boiler` (temperature model, views). Run all commands from `server/`.

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
../env/bin/python manage.py migrate
../env/bin/python manage.py runserver
```

## Server specifics (non-obvious)
- `LoginRequiredMiddleware` is enabled globally, so every view requires login; allauth routes live under `/accounts/` and `LOGIN_REDIRECT_URL='/boiler/'`.
- `SOCIALACCOUNT_ONLY=True`, email verification off; Google is the only sign-in provider. OAuth client ID/secret are stored as a `SocialApp` row in the DB (configure via admin), not in settings.
- `webapp/signals.py` auto-promotes the **first** user to sign up to staff/superuser (wired via `WebappConfig.ready()`). Don't add a second automatic-admin path.
- CSP is enforced by `SECURE_CSP` + `django.middleware.csp.ContentSecurityPolicyMiddleware`. The Google sign-in hash and `cdn.jsdelivr.net` are allowlisted; changing the inline script in `templates/account/login.html` likely requires updating the SHA-256 hash in `settings.py`.
- `TemperatureReading.temperature` stores °C **doubled as an integer**; use `real_temperature()` to get the actual value.
- `server/m6675.py` is a MAX6675 SPI thermocouple driver (gpiozero/spidev/lgpio); it is hardware-dependent and not usable on a non-Pi machine.
- Project-level `server/templates/` overrides allauth templates (`account/login.html`, `allauth/...`).
- `db.sqlite3` is gitignored. Settings are dev-only: `DEBUG=True`, hardcoded `SECRET_KEY`, empty `ALLOWED_HOSTS`.
