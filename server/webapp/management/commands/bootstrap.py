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
