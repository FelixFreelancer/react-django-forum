from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone
from django.utils.translation import ugettext as _
from django.utils.translation import ugettext_lazy

from misago.acl import add_acl
from misago.conf import settings
from misago.core.shortcuts import paginate, pagination_dict
from misago.readtracker import threadstracker
from misago.readtracker.dates import get_cutoff_date
from misago.threads.models import Post, Thread
from misago.threads.participants import make_participants_aware
from misago.threads.permissions import exclude_invisible_posts, exclude_invisible_threads
from misago.threads.serializers import ThreadsListSerializer
from misago.threads.subscriptions import make_subscription_aware
from misago.threads.utils import add_categories_to_items


__all__ = ['ForumThreads', 'PrivateThreads', 'filter_read_threads_queryset']

LISTS_NAMES = {
    'all': None,
    'my': ugettext_lazy("Your threads"),
    'new': ugettext_lazy("New threads"),
    'unread': ugettext_lazy("Unread threads"),
    'subscribed': ugettext_lazy("Subscribed threads"),
    'unapproved': ugettext_lazy("Unapproved content"),
}

LIST_DENIED_MESSAGES = {
    'my': ugettext_lazy("You have to sign in to see list of threads that you have started."),
    'new': ugettext_lazy("You have to sign in to see list of threads you haven't read."),
    'unread': ugettext_lazy("You have to sign in to see list of threads with new replies."),
    'subscribed': ugettext_lazy("You have to sign in to see list of threads you are subscribing."),
    'unapproved': ugettext_lazy("You have to sign in to see list of threads with unapproved posts."),
}


class ViewModel(object):
    def __init__(self, request, category, list_type, page):
        self.allow_see_list(request, category, list_type)

        category_model = category.unwrap()

        base_queryset = self.get_base_queryset(request, category.categories, list_type)
        base_queryset = base_queryset.select_related('starter', 'last_poster')

        threads_categories = [category_model] + category.subcategories

        threads_queryset = self.get_remaining_threads_queryset(
            base_queryset, category_model, threads_categories
        )

        list_page = paginate(
            threads_queryset, page, settings.MISAGO_THREADS_PER_PAGE, settings.MISAGO_THREADS_TAIL
        )
        paginator = pagination_dict(list_page)

        if list_page.number > 1:
            threads = list(list_page.object_list)
        else:
            pinned_threads = list(
                self.get_pinned_threads(base_queryset, category_model, threads_categories)
            )
            threads = list(pinned_threads) + list(list_page.object_list)

        add_categories_to_items(category_model, category.categories, threads)
        add_acl(request.user, threads)
        make_subscription_aware(request.user, threads)

        if list_type in ('new', 'unread'):
            # we already know all threads on list are unread
            for thread in threads:
                thread.is_read = False
                thread.is_new = True
        else:
            threadstracker.make_read_aware(request.user, threads)

        self.filter_threads(request, threads)

        # set state on object for easy access from hooks
        self.category = category
        self.threads = threads
        self.list_type = list_type
        self.paginator = paginator

    def allow_see_list(self, request, category, list_type):
        if list_type not in LISTS_NAMES:
            raise Http404()

        if request.user.is_anonymous:
            if list_type in LIST_DENIED_MESSAGES:
                raise PermissionDenied(LIST_DENIED_MESSAGES[list_type])
        else:
            has_permission = request.user.acl_cache['can_see_unapproved_content_lists']
            if list_type == 'unapproved' and not has_permission:
                raise PermissionDenied(
                    _("You don't have permission to see unapproved content lists.")
                )

    def get_list_name(self, list_type):
        return LISTS_NAMES[list_type]

    def get_base_queryset(self, request, threads_categories, list_type):
        return get_threads_queryset(
            request.user,
            threads_categories,
            list_type,
        ).order_by('-last_post_id')

    def get_pinned_threads(self, queryset, category, threads_categories):
        return []

    def get_remaining_threads_queryset(self, queryset, category, threads_categories):
        return []

    def filter_threads(self, request, threads):
        pass  # hook for custom thread types to add features to extend threads

    def get_frontend_context(self):
        context = {
            'THREADS': {
                'results': ThreadsListSerializer(self.threads, many=True).data,
                'subcategories': [c.pk for c in self.category.children],
            },
        }

        context['THREADS'].update(self.paginator)
        return context

    def get_template_context(self):
        return {
            'list_name': self.get_list_name(self.list_type),
            'list_type': self.list_type,
            'threads': self.threads,
            'paginator': self.paginator,
        }


class ForumThreads(ViewModel):
    def get_pinned_threads(self, queryset, category, threads_categories):
        if category.level:
            return list(queryset.filter(weight=2)
                        ) + list(queryset.filter(weight=1, category__in=threads_categories))
        else:
            return queryset.filter(weight=2)

    def get_remaining_threads_queryset(self, queryset, category, threads_categories):
        if category.level:
            return queryset.filter(
                weight=0,
                category__in=threads_categories,
            )
        else:
            return queryset.filter(
                weight__lt=2,
                category__in=threads_categories,
            )


class PrivateThreads(ViewModel):
    def get_base_queryset(self, request, threads_categories, list_type):
        queryset = super().get_base_queryset(request, threads_categories, list_type)

        # limit queryset to threads we are participant of
        participated_threads = request.user.threadparticipant_set.values('thread_id')

        if request.user.acl_cache['can_moderate_private_threads']:
            queryset = queryset.filter(Q(id__in=participated_threads) | Q(has_reported_posts=True))
        else:
            queryset = queryset.filter(id__in=participated_threads)

        return queryset

    def get_remaining_threads_queryset(self, queryset, category, threads_categories):
        return queryset.filter(category__in=threads_categories)

    def filter_threads(self, request, threads):
        make_participants_aware(request.user, threads)


def get_threads_queryset(user, categories, list_type):
    queryset = exclude_invisible_threads(user, categories, Thread.objects)

    if list_type == 'all':
        return queryset
    else:
        return filter_threads_queryset(user, categories, list_type, queryset)


def filter_threads_queryset(user, categories, list_type, queryset):
    if list_type == 'my':
        return queryset.filter(starter=user)
    elif list_type == 'subscribed':
        subscribed_threads = user.subscription_set.values('thread_id')
        return queryset.filter(id__in=subscribed_threads)
    elif list_type == 'unapproved':
        return queryset.filter(has_unapproved_posts=True)
    elif list_type in ('new', 'unread'):
        return filter_read_threads_queryset(user, categories, list_type, queryset)
    else:
        return queryset


def filter_read_threads_queryset(user, categories, list_type, queryset):
    # grab cutoffs for categories
    cutoff_date = get_cutoff_date(user)

    visible_posts = Post.objects.filter(posted_on__gt=cutoff_date)
    visible_posts = exclude_invisible_posts(user, categories, visible_posts)

    queryset = queryset.filter(id__in=visible_posts.distinct().values('thread'))

    read_posts = visible_posts.filter(id__in=user.postread_set.values('post'))

    if list_type == 'new':
        # new threads have no entry in reads table
        return queryset.exclude(id__in=read_posts.distinct().values('thread'))

    if list_type == 'unread':
        # unread threads were read in past but have new posts
        unread_posts = visible_posts.exclude(id__in=user.postread_set.values('post'))
        queryset = queryset.filter(id__in=read_posts.distinct().values('thread'))
        queryset = queryset.filter(id__in=unread_posts.distinct().values('thread'))
        return queryset
