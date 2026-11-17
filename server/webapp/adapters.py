from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class BootstrapSocialAccountAdapter(DefaultSocialAccountAdapter):
    """No account may create itself.

    Accounts are pre-created by `manage.py bootstrap` (or later by the admin).
    The admin signs in through allauth's email authentication, which resolves
    the pre-created user before this hook is ever consulted.
    """

    def is_open_for_signup(self, request, sociallogin) -> bool:
        return False
