from django.contrib.auth import get_user_model
from django.core.management.base import CommandError, BaseCommand

from misago.conf import settings
from misago.core.pgutils import chunk_queryset

from misago.users.permissions import can_delete_own_account


UserModel = get_user_model()


class Command(BaseCommand):
    help = (
        "Deletes accounts of users that have requested it. "
        "Leaves their content behind, but anonymises it."
    )

    def handle(self, *args, **options):
        users_deleted = 0
        
        queryset = UserModel.objects.filter(is_deleting_account=True)

        for user in chunk_queryset(queryset):
            if can_delete_own_account(user, user):
                user.delete()
                users_deleted += 1

        self.stdout.write("Deleted users: {}".format(users_deleted))
