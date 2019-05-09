from misago.threads.models import Post
from misago.threads.permissions import exclude_invisible_posts

from .dates import get_cutoff_date


def make_read_aware(user, threads):
    if not threads:
        return

    if not hasattr(threads, '__iter__'):
        threads = [threads]

    make_read(threads)

    if user.is_anonymous:
        return

    categories = [t.category for t in threads]

    queryset = Post.objects.filter(
        thread__in=threads,
        posted_on__gt=get_cutoff_date(user),
    ).values_list('thread', flat=True).distinct()

    queryset = queryset.exclude(id__in=user.postread_set.values('post'))
    queryset = exclude_invisible_posts(user, categories, queryset)

    unread_threads = list(queryset)

    for thread in threads:
        if thread.pk in unread_threads:
            thread.is_read = False
            thread.is_new = True


def make_read(threads):
    for thread in threads:
        thread.is_read = True
        thread.is_new = False
