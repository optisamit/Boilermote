from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialLogin, SocialApp
from allauth.socialaccount.providers import registry

from .adapters import BootstrapSocialAccountAdapter
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

    def test_stores_a_mixed_case_email_lowercased(self):
        user, _ = ensure_admin_user("Admin@Example.com")
        self.assertEqual(user.email, "admin@example.com")
        self.assertEqual(user.username, "admin@example.com")

    def test_normalizes_the_email_when_promoting_an_existing_user(self):
        existing = get_user_model().objects.create_user(
            "oleksandr", email="Admin@Example.com"
        )
        user, created = ensure_admin_user("admin@example.com")
        self.assertFalse(created)
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(user.email, "admin@example.com")


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

    def test_email_authentication_resolves_a_mixed_case_admin(self):
        # Google may report the address in any case; allauth lowercases the
        # query, so the stored email must be lowercase or the admin is locked
        # out of their own install (signup is closed for everyone).
        user, _ = ensure_admin_user("Admin@Example.com")
        sociallogin = self._social_login("admin@example.com")
        sociallogin.lookup()
        self.assertEqual(sociallogin.user.pk, user.pk)


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
