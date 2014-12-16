from django.conf.urls import patterns, url

from .api import AccessRequestDetail, AccessRequestList, SecretDetail, SecretList, \
    SecretRevisionDetail, data_get


urlpatterns = patterns(
    '',
    url(
        r'^access-requests/$',
        AccessRequestList.as_view(),
        name='api.access-request_list',
    ),
    url(
        r'^access-requests/(?P<pk>\d+)/$',
        AccessRequestDetail.as_view(),
        name='api.access-request_detail',
    ),
    url(
        r'^secrets/$',
        SecretList.as_view(),
        name='api.secret_list',
    ),
    url(
        r'^secrets/(?P<pk>\d+)/$',
        SecretDetail.as_view(),
        name='api.secret_detail',
    ),
    url(
        r'^secret-revisions/(?P<pk>\d+)/$',
        SecretRevisionDetail.as_view(),
        name='api.secret-revision_detail',
    ),
    url(
        r'^secret-revisions/(?P<pk>\d+)/data$',
        data_get,
        name='api.secret-revision_data',
    ),
)
