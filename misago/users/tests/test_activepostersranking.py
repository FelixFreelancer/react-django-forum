from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from misago.categories.models import Category
from misago.core import threadstore
from misago.core.cache import cache
from misago.threads.testutils import post_thread
from misago.users.activepostersranking import (
    build_active_posters_ranking, get_active_posters_ranking)
from misago.users.testutils import AuthenticatedUserTestCase


UserModel = get_user_model()


class TestActivePostersRanking(AuthenticatedUserTestCase):
    def setUp(self):
        super().setUp()

        cache.clear()
        threadstore.clear()

        self.category = Category.objects.get(slug='first-category')

    def tearDown(self):
        super().tearDown()

        cache.clear()
        threadstore.clear()

    def test_get_active_posters_ranking(self):
        """get_active_posters_ranking returns list of active posters"""
        # no posts, empty tanking
        empty_ranking = get_active_posters_ranking()

        self.assertEqual(empty_ranking['users'], [])
        self.assertEqual(empty_ranking['users_count'], 0)

        # other user that will be posting
        other_user = UserModel.objects.create_user("OtherUser", "other@user.com", "pass123")

        # lurker user that won't post anything
        UserModel.objects.create_user("Lurker", "lurker@user.com", "pass123")

        # unranked user that posted something 400 days ago
        unranked_user = UserModel.objects.create_user(
            "UnrankedUser", "unranked@user.com", "pass123"
        )

        started_on = timezone.now() - timedelta(days=400)
        post_thread(self.category, poster=unranked_user, started_on=started_on)

        # Start testing scenarios
        post_thread(self.category, poster=other_user)

        build_active_posters_ranking()
        ranking = get_active_posters_ranking()

        self.assertEqual(ranking['users'], [other_user])
        self.assertEqual(ranking['users_count'], 1)

        # two users in ranking
        post_thread(self.category, poster=self.user)
        post_thread(self.category, poster=self.user)

        build_active_posters_ranking()
        ranking = get_active_posters_ranking()

        self.assertEqual(ranking['users'], [self.user, other_user])
        self.assertEqual(ranking['users_count'], 2)

        self.assertEqual(ranking['users'][0].score, 2)
        self.assertEqual(ranking['users'][1].score, 1)

        # disabled users are not ranked
        disabled = UserModel.objects.create_user("DisabledUser", "disabled@user.com", "pass123")

        disabled.is_active = False
        disabled.save()

        post_thread(self.category, poster=disabled)
        post_thread(self.category, poster=disabled)
        post_thread(self.category, poster=disabled)

        disabled.posts = 3
        disabled.save()

        build_active_posters_ranking()
        ranking = get_active_posters_ranking()

        self.assertEqual(ranking['users'], [self.user, other_user])
        self.assertEqual(ranking['users_count'], 2)

        self.assertEqual(ranking['users'][0].score, 2)
        self.assertEqual(ranking['users'][1].score, 1)
