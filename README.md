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
