from django.contrib.auth import get_user_model
from django.dispatch import receiver

from allauth.account.signals import user_signed_up


@receiver(user_signed_up)
def promote_first_user(sender, request, user, **kwargs):
    if get_user_model().objects.count() <= 1:
        user.is_staff = True
        user.is_superuser = True
        user.save()