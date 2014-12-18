# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from json import dumps
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.shortcuts import get_object_or_404, render
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView

from ..audit.auditlog import log
from .forms import AddCCForm, AddFileForm, PasswordForm
from .models import AccessRequest, Secret

ACCESS_STR_IDS = {
    'ACCESS_POLICY_ANY': str(Secret.ACCESS_POLICY_ANY),
    'ACCESS_POLICY_REQUEST': str(Secret.ACCESS_POLICY_REQUEST),
    'ACCESS_POLICY_HIDDEN': str(Secret.ACCESS_POLICY_HIDDEN),
}
CONTENT_TYPE_FORMS = {
    'cc': AddCCForm,
    'file': AddFileForm,
    'password': PasswordForm,
}
CONTENT_TYPE_IDS = {
    'cc': Secret.CONTENT_CC,
    'file': Secret.CONTENT_FILE,
    'password': Secret.CONTENT_PASSWORD,
}
CONTENT_TYPE_IDENTIFIERS = {v: k for k, v in CONTENT_TYPE_IDS.items()}
_CONTENT_TYPES = dict(Secret.CONTENT_CHOICES)
CONTENT_TYPE_NAMES = {
    'cc': _CONTENT_TYPES[Secret.CONTENT_CC],
    'file': _CONTENT_TYPES[Secret.CONTENT_FILE],
    'password': _CONTENT_TYPES[Secret.CONTENT_PASSWORD],
}


def _patch_post_data(POST, fields):
    """
    Select2 passes in selected values as CSV instead of as a real
    multiple value field, so we need to split them before any validation
    takes place.
    """
    POST = POST.copy()
    for csv_field in fields:
        if POST.getlist(csv_field) == ['']:
            del POST[csv_field]
        else:
            POST.setlist(
                csv_field,
                POST.getlist(csv_field)[0].split(","),
            )
    return POST


@login_required
def access_request_create(request, pk):
    secret = Secret.objects.get(pk=pk)
    if not secret.is_visible_to_user(request.user):
        raise Http404
    try:
        AccessRequest.objects.get(
            requester=request.user,
            secret=secret,
            status=AccessRequest.STATUS_PENDING,
        )
    except AccessRequest.DoesNotExist:
        if request.method == 'POST' and not secret.is_readable_by_user(request.user):
            access_request = AccessRequest()
            access_request.reason_request = request.POST['reason']
            access_request.requester = request.user
            access_request.secret = secret
            access_request.save()
            access_request.assign_reviewers()
    return HttpResponseRedirect(secret.get_absolute_url())


@login_required
@require_http_methods(["POST"])
def access_request_review(request, pk, action):
    access_request = get_object_or_404(
        AccessRequest,
        pk=pk,
        status=AccessRequest.STATUS_PENDING,
    )
    if not request.user.is_superuser and not request.user in access_request.reviewers.all():
        raise PermissionDenied()

    if action == 'allow':
        access_request.approve(request.user)
    else:
        access_request.reject(request.user, reason=request.POST.get('reason', None))

    return HttpResponseRedirect(reverse('secrets.access_request-list'))


class AccessRequestDetail(DetailView):
    context_object_name = 'access_request'
    model = AccessRequest
    template_name = "secrets/accessrequest_detail.html"

    def get_object(self):
        if self.request.user.is_superuser:
            return get_object_or_404(
                AccessRequest,
                pk=self.kwargs['pk'],
                status=AccessRequest.STATUS_PENDING,
            )
        else:
            return get_object_or_404(
                AccessRequest,
                pk=self.kwargs['pk'],
                reviewers=self.request.user,
                status=AccessRequest.STATUS_PENDING,
            )


class AccessRequestList(ListView):
    context_object_name = 'access_requests'
    template_name = "secrets/accessrequests_list.html"

    def get_context_data(self, **kwargs):
        queryset = self.get_queryset()
        context = super(AccessRequestList, self).get_context_data(**kwargs)
        context['reviewable'] = queryset.exclude(requester=self.request.user)
        context['pending_review'] = queryset.filter(requester=self.request.user)
        return context

    def get_queryset(self):
        queryset = AccessRequest.get_all_readable_by_user(self.request.user)
        return queryset.filter(status=AccessRequest.STATUS_PENDING)


class SecretAdd(CreateView):
    def form_valid(self, form):
        secret = Secret()
        secret.content_type = CONTENT_TYPE_IDS[self.kwargs['content_type']]
        secret.created_by = self.request.user

        for attr in ('access_policy', 'description', 'name', 'needs_changing_on_leave', 'url',
                     'username'):
            if attr in form.cleaned_data:
                setattr(secret, attr, form.cleaned_data[attr])
        secret.save()

        for attr in ('allowed_groups', 'allowed_users'):
            setattr(secret, attr, form.cleaned_data[attr])
        secret.save()

        if secret.content_type == Secret.CONTENT_PASSWORD:
            plaintext_data = form.cleaned_data['password']
        secret.set_data(self.request.user, plaintext_data)

        return HttpResponseRedirect(secret.get_absolute_url())

    def get_context_data(self, **kwargs):
        context = super(SecretAdd, self).get_context_data(**kwargs)
        try:
            context['pretty_content_type'] = CONTENT_TYPE_NAMES[self.kwargs['content_type']]
        except KeyError:
            raise Http404
        context.update(ACCESS_STR_IDS)
        return context

    def get_form_class(self):
        return CONTENT_TYPE_FORMS[self.kwargs['content_type']]

    def get_template_names(self):
        return "secrets/secret_addedit_{}.html".format(self.kwargs['content_type'])

    def post(self, request, *args, **kwargs):
        request.POST = _patch_post_data(request.POST, ('allowed_groups', 'allowed_users'))
        return super(SecretAdd, self).post(request, *args, **kwargs)


class SecretEdit(UpdateView):
    context_object_name = 'secret'

    def form_valid(self, form):
        secret = self.object

        for attr in ('access_policy', 'description', 'name', 'needs_changing_on_leave', 'url',
                     'username'):
            if attr in form.cleaned_data:
                setattr(secret, attr, form.cleaned_data[attr])
        secret.save()

        for attr in ('allowed_groups', 'allowed_users'):
            setattr(secret, attr, form.cleaned_data[attr])
        secret.save()

        if secret.content_type == Secret.CONTENT_PASSWORD and form.cleaned_data['password']:
            secret.set_data(self.request.user, form.cleaned_data['password'])

        return HttpResponseRedirect(secret.get_absolute_url())

    def get_context_data(self, **kwargs):
        context = super(SecretEdit, self).get_context_data(**kwargs)
        context['pretty_content_type'] = self.object.get_content_type_display()
        context.update(ACCESS_STR_IDS)
        return context

    def get_form_class(self):
        return CONTENT_TYPE_FORMS[CONTENT_TYPE_IDENTIFIERS[self.object.content_type]]

    def get_object(self, queryset=None):
        secret = get_object_or_404(Secret, pk=self.kwargs['pk'])
        secret.check_access(self.request.user)
        return secret

    def get_template_names(self):
        return "secrets/secret_addedit_{}.html".format(CONTENT_TYPE_IDENTIFIERS[self.object.content_type])

    def post(self, request, *args, **kwargs):
        request.POST = _patch_post_data(request.POST, ('allowed_groups', 'allowed_users'))
        return super(SecretEdit, self).post(request, *args, **kwargs)


@login_required
def secret_delete(request, pk):
    secret = get_object_or_404(Secret, pk=pk)
    secret.check_access(request.user)
    if request.method == 'POST':
        log(_(
                "{user} deleted '{name}' ({id}:{revision})"
            ).format(
                id=secret.id,
                name=secret.name,
                revision=secret.current_revision.id,
                user=request.user.username,
            ),
            actor=request.user,
            level='info',
            secret=secret,
            secret_revision=secret.current_revision,
        )
        secret.status = Secret.STATUS_DELETED
        secret.save()
        return HttpResponseRedirect(reverse('secrets.secret-list') + "?" + urlencode([("search", secret.name.encode('utf-8'))]))
    else:
        return render(request, "secrets/secret_delete.html", {'secret': secret})


class SecretDetail(DetailView):
    context_object_name = 'secret'
    model = Secret
    template_name = "secrets/secret_detail.html"

    def get_context_data(self, **kwargs):
        context = super(SecretDetail, self).get_context_data(**kwargs)
        secret = self.get_object()
        context['readable'] = secret.is_readable_by_user(self.request.user)
        context['secret_url'] = reverse(
            'api.secret-revision_data',
            kwargs={'pk': secret.current_revision.pk},
        )
        if context['readable']:
            context['placeholder'] = secret.current_revision.length * "•"
        else:
            try:
                context['access_request'] = AccessRequest.objects.get(
                    secret=secret,
                    status=AccessRequest.STATUS_PENDING,
                    requester=self.request.user,
                )
            except AccessRequest.DoesNotExist:
                context['access_request'] = None
        return context

    def get_object(self):
        object = super(SecretDetail, self).get_object()
        if not object.is_visible_to_user(self.request.user):
            raise Http404
        return object


class SecretList(ListView):
    context_object_name = 'secrets'
    template_name = "secrets/secret_list.html"

    def get_context_data(self, **kwargs):
        context = super(SecretList, self).get_context_data(**kwargs)
        context['readable_secrets'] = Secret.get_all_readable_by_user(self.request.user)
        context['search_term'] = self.request.GET.get('search', None)
        return context

    def get_queryset(self):
        if "search" in self.request.GET:
            return Secret.get_search_results(self.request.user, self.request.GET['search'])
        else:
            return Secret.get_all_visible_to_user(self.request.user)


@login_required
@require_http_methods(["POST"])
def secret_share(request, pk):
    secret = get_object_or_404(Secret, pk=pk)
    secret.check_access(request.user)

    request.POST = _patch_post_data(request.POST, ('share_groups', 'share_users'))

    groups = []
    for group_id in request.POST.getlist('share_groups', []):
        groups.append(get_object_or_404(Group, pk=int(group_id)))

    users = []
    for user_id in request.POST.getlist('share_users', []):
        users.append(get_object_or_404(User, pk=int(user_id)))

    for group in groups:
        log(
            _("{actor} shared '{secret}' with {group}").format(
                actor=request.user,
                group=group.name,
                secret=secret.name,
            ),
            actor=request.user,
            group=group,
            secret=secret,
        )
        secret.allowed_groups.add(group)
        # TODO email with additional message field

    for user in users:
        log(
            _("{actor} shared '{secret}' with {user}").format(
                actor=request.user,
                secret=secret.name,
                user=user.username,
            ),
            actor=request.user,
            secret=secret,
            user=user,
        )
        secret.allowed_users.add(user)
        # TODO email with additional message field

    return HttpResponseRedirect(secret.get_absolute_url())


@login_required
@require_http_methods(["GET"])
def secret_search(request):
    search_term = request.GET['q']
    search_result = []
    all_secrets = Secret.get_all_visible_to_user(request.user)
    filtered_secrets = list(all_secrets.filter(name__icontains=search_term)[:20])
    unreadable_secrets = filtered_secrets[:]
    sorted_secrets = []

    # sort readable passwords to top...
    for secret in filtered_secrets:
        if secret.is_readable_by_user(request.user):
            sorted_secrets.append((secret, "unlock"))
            unreadable_secrets.remove(secret)

    # and others to the bottom
    for secret in unreadable_secrets:
        sorted_secrets.append((secret, "lock"))

    for secret, icon in sorted_secrets:
        search_result.append({
            'name': secret.name,
            'url': reverse('secrets.secret-detail', kwargs={'pk': secret.pk}),
            'icon': icon,
        })

    return HttpResponse(dumps(search_result), content_type="application/json")

