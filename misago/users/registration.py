from django.utils.translation import ugettext as _

from misago.conf import settings
from misago.core.mail import mail_user
from misago.legal.models import Agreement
from misago.legal.utils import save_user_agreement_acceptance
from misago.users.tokens import make_activation_token


def send_welcome_email(request, user):
    mail_subject = _("Welcome on %(forum_name)s forums!")
    mail_subject = mail_subject % {'forum_name': settings.forum_name}

    if not user.requires_activation:
        mail_user(user, mail_subject, 'misago/emails/register/complete')
        return

    activation_token = make_activation_token(user)

    activation_by_admin = user.requires_activation_by_admin
    activation_by_user = user.requires_activation_by_user

    mail_user(
        user,
        mail_subject,
        'misago/emails/register/inactive',
        context={
            'activation_token': activation_token,
            'activation_by_admin': activation_by_admin,
            'activation_by_user': activation_by_user,
        }
    )


def save_user_agreements(user, form):
    if not form.agreements:
        return

    for field_name in form.agreements.keys():
        agreement_id = form.cleaned_data[field_name]
        agreement = Agreement.objects.get(id=agreement_id)
        save_user_agreement_acceptance(user, agreement)

    user.save(update_fields=['agreements'])


def get_registration_result_json(user):
    activation_method = 'active'
    if user.requires_activation_by_admin:
        activation_method = 'admin'
    elif user.requires_activation_by_user:
        activation_method = 'user'

    return {
        'activation': activation_method,
        'email': user.email,
        'username': user.username,
    }