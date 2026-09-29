"""The staff door, and the base every `ModelAdmin` in the product inherits.

House rule 21: **the admin is a door, and every door calls services.** Django's
default admin writes with `obj.save()`, which means a change made by a support
agent skips the validation, the authorization, the events and the audit trail
that the same change through the API would go through. Two write paths with
different rules is the shape of the incident nobody can reconstruct afterwards.

`ServiceModelAdmin` closes that:

* `save_model` and `delete_model` delegate to a service, named by
  `service_for(action)`, with the acting `Actor` and the acting tenant;
* `get_queryset` narrows a tenant-scoped model to the tenant the staff member
  is acting in — and an **org-scoped** one to the subtree of the hat they are
  wearing — so `for_tenant(...).visible_to(...)` holds here as it does
  everywhere else;
* `door="admin"` is bound for the request, so an audit row says where the
  change came from;
* a service's **refusal** is mapped here as `config/api.py` maps it for REST
  and `core.mcp` for the machine door — `messages.error` carrying
  `wire_refusal`'s line, and the changelist again. A refusal that escaped as an
  exception was a 500 that also took its own `AuditEntry` down with it, because
  Django wraps the whole POST in one transaction.

A subclass that has no service for an action says so by returning `None`, and
gets the ordinary Django behaviour with a comment saying why — **unless the
model is one something guards** (tenant-scoped, or on `WALL_GUARDED`), in which
case the missing wiring is a refusal rather than a quiet fallthrough
(`refuse_unwired`). A subclass that wants a genuinely read-only table uses
`ReadOnlyModelAdmin` below; a model that declared `append_only = True` gets no
change and no delete from any subclass that has not deliberately said otherwise.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse

from apps.core import bridge
from apps.core.actor import Actor, actor_from_request
from apps.core.audit import AuditEntry
from apps.core.exceptions import DomainError, refusal_message, wire_refusal
from apps.core.models import (
    Invitation,
    Membership,
    Organization,
    ScopedManager,
    ScopedQuerySet,
    Tenant,
    is_append_only,
    is_org_scoped,
)

Action = Literal["create", "update", "delete"]

# Models whose writes a *rule* guards rather than the tenancy: the escalation
# wall (`core.services._refuse_escalation`) for `Membership`, and the tree's own
# services for `Organization`, whose `path` and `parent` house rule 24 refuses
# anywhere else. Named here as a tuple rather than sniffed, because "is there a
# rule about this model" is not a property of its fields — and a product that
# grows another such model adds it here, in one place, with the reason.
#
# Tenant-scoped models are guarded too and are recognised from their manager;
# see `is_guarded` below.
WALL_GUARDED: tuple[type[Model], ...] = (Membership, Organization)

# Where a refusal caught mid-request is remembered, so the hooks Django calls
# *after* `save_model` can see that nothing happened. An attribute on the
# request and not on the admin instance, because a `ModelAdmin` is a singleton
# the whole site shares and a refusal belongs to one request; the same reason
# `core.actor` keeps the resolved token there.
REFUSAL_ATTR = "_service_refusal"


def is_guarded(model: type[Model]) -> bool:
    """Whether an unwired admin write on this model is a bug rather than a choice.

    Two populations, both read rather than remembered: anything the tenancy
    narrows (a `ScopedManager` is what `TenantScopedModel` installs), and the
    rows a named rule guards (`WALL_GUARDED`). For those, Django's default
    `obj.save()` is not a lesser door — it is a *second* door with different
    rules, which is the shape a bare `obj.save()` here actually was.

    Everything else keeps the ordinary fallthrough, and that is load-bearing:
    `accounts.UserAdmin` returns `None` on purpose, because taking the add form
    over would mean taking password validation over with it.
    """
    return isinstance(model._default_manager, ScopedManager) or issubclass(model, WALL_GUARDED)


class ServiceModelAdmin[M: Model](admin.ModelAdmin[M]):
    """A `ModelAdmin` whose writes go where every other door's writes go."""

    def service_for(self, action: Action) -> Any | None:
        """The service that performs this action, or `None` for Django's default.

        Subclasses implement this. Returning `None` is a deliberate choice with
        a stated reason, not a shortcut — a model with no service behind its
        admin is a model two doors can change differently.
        """
        return None

    def acting(self, request: HttpRequest) -> tuple[Actor, Tenant | None]:
        """Who the staff member is, and which tenant they are acting in."""
        actor = actor_from_request(request)
        return actor, actor.tenant

    def get_queryset(self, request: HttpRequest) -> QuerySet[M]:
        """Scoped models are read through `for_tenant`, here as everywhere —
        and org-scoped ones through `visible_to` as well.

        The admin used to be the documented exception — "staff act across
        tenants" — and that is exactly the exemption that turns a support tool
        into the one place tenancy does not hold. A staff member who needs
        another tenant switches to it with `X-Tenant`, or another part of one
        with `X-Org`, which are things they did and which the audit trail
        records.

        The second half is not optional and not an admin nicety: an org-scoped
        model read with `for_tenant` alone would make this the one door in the
        product where a branch's hat sees the whole tenant. Whether the second
        half is needed is read off the model — `visible_to` refuses a model
        with no `organization` — rather than remembered per subclass.
        """
        manager = self.model._default_manager
        if isinstance(manager, ScopedManager):
            actor = actor_from_request(request)
            # `ScopedQuerySet`, not the plain `QuerySet` the admin's own
            # annotations describe — narrowed here so that `visible_to` is
            # visible to the type checker as well as to the reader.
            scoped: ScopedQuerySet[Any] = manager.for_tenant(actor.tenant)
            if is_org_scoped(self.model):
                scoped = scoped.visible_to(actor)
            return cast(QuerySet[M], scoped)
        return super().get_queryset(request)

    def refuse_unwired(self, action: Action) -> None:
        """No service, on a model something guards: stop, and say what is missing.

        The alternative is `super().save_model()` writing the
        row with `obj.save()`, past the escalation wall, past the tenancy, and
        with no audit row to say it happened. A silent second write path is
        worse than a broken admin page, because a broken page gets fixed.

        `ImproperlyConfigured` and not a `DomainError`: nobody was refused
        permission. The wiring is missing, and that is a message for whoever
        wrote the subclass rather than for whoever clicked Save.
        """
        if not is_guarded(self.model):
            return
        raise ImproperlyConfigured(
            f"{type(self).__name__}.service_for({action!r}) returned None for "
            f"{self.model._meta.label}, which is tenant-scoped or wall-guarded. "
            f"Falling through to obj.save() would write it past the service that "
            f"authorizes and audits it. Name the service in service_for(), or make "
            f"the admin read-only with core.admin.ReadOnlyModelAdmin."
        )

    # --- The refusal mapper: house rule 14, for the door a human drives ------
    #
    # Every other door maps `DomainError` to its own vocabulary — `config/api.py`
    # to a status code and a JSON body, `core.mcp.tool_call` to a `ToolError`
    # line. The admin had no mapper at all, so a refusal escaped
    # `changeform_view` as an exception and Django answered 500. It was correct
    # and it looked like an outage, and it cost more than looks: `changeform_view`
    # wraps the whole POST in `transaction.atomic`, so the `AuditEntry` the
    # `@service` decorator writes on its refusal path was rolled back with
    # everything else on the way out. The refusal was loud in the console and
    # invisible in the trail.
    #
    # Returning normally fixes both halves at once. Nothing is composed here:
    # `wire_refusal` builds the body and `refusal_message` renders the line, the
    # same two functions the REST and MCP doors use, so the screen and the
    # assistant say the same thing about one refusal.
    #
    # DOES NOT COVER — declared: Django's own admin-history `LogEntry`. The view
    # writes it around the hook this class owns (before `delete_model`, after
    # `save_model`), so a refused write still leaves a row in
    # `/admin/.../history/`. Re-ordering Django's view is not this door's
    # refusal grammar, and the trail this product reasons from — `AuditEntry` —
    # is correct. Nor is a *programming* error mapped: `refuse_unwired` raises
    # `ImproperlyConfigured` and that still 500s, deliberately, because it is a
    # message for whoever wrote the subclass rather than for whoever clicked
    # Save.

    def refusal(self, request: HttpRequest) -> DomainError | None:
        """The refusal this request already met, if it met one."""
        refused = getattr(request, REFUSAL_ATTR, None)
        return refused if isinstance(refused, DomainError) else None

    def render_refusal(self, request: HttpRequest, exc: DomainError) -> None:
        """Say no, where the person who clicked Save is looking."""
        setattr(request, REFUSAL_ATTR, exc)
        messages.error(request, refusal_message(wire_refusal(exc), extra=False))

    def message_user(self, request: HttpRequest, message: Any, *args: Any, **kwargs: Any) -> Any:
        """Drop a success message on a request that was refused.

        `response_delete` and the `delete_selected` action both announce success
        unconditionally, from Django's code rather than from ours. A page saying
        "deleted successfully" above a red refusal is worse than either alone.
        """
        level = kwargs.get("level", args[0] if args else messages.INFO)
        if level == messages.SUCCESS and self.refusal(request) is not None:
            return None
        return super().message_user(request, message, *args, **kwargs)

    def save_related(self, request: HttpRequest, form: Any, formsets: Any, change: bool) -> None:
        """Nothing to relate to: the row was never written."""
        if self.refusal(request) is not None:
            return
        super().save_related(request, form, formsets, change)

    def response_add(
        self, request: HttpRequest, obj: M, post_url_continue: str | None = None
    ) -> HttpResponse:
        """Back to the changelist with the message, whichever Save was clicked.

        Explicitly, rather than by letting `super()` run: "Save and continue
        editing" would otherwise redirect to the change form of a row that was
        never inserted.
        """
        if self.refusal(request) is not None:
            return self.response_post_save_add(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request: HttpRequest, obj: M) -> HttpResponse:
        """The other half of the same choice."""
        if self.refusal(request) is not None:
            return self.response_post_save_change(request, obj)
        return super().response_change(request, obj)

    def has_view_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        """**The admin asks the same question every other door asks** (rule 21).

        Since Phase R a read is a permission (ADR core-27), and this is the door
        that would otherwise have been left out: `get_queryset` scopes the rows
        by tenant and hat, which answers *which rows* and has never answered
        *whether this kind at all*. Without this hook the changelist of a kind
        the acting hat may not read renders as an EMPTY PAGE — the one refusal
        shape this system refuses everywhere else, because an empty list and a
        refusal are different facts and a support agent cannot tell them apart.

        `allows` rather than `require`: Django's admin asks for a boolean and
        renders its own 403 from it, so raising here would replace a 403 page
        with a 500. The sentence a refused caller reads on the other two doors
        comes from `refusal_sentence`; the admin's own template is Django's.

        **A model with no kind keeps today's answer.** `kind_of` returns `None`
        for anything the registry does not name — `AuditEntry`'s siblings, a
        third-party table registered here — and those are staff-only surfaces
        whose gate is `is_staff` and the tenancy scoping, exactly as before.
        """
        from apps.core.authz import allows, kind_of

        kind = kind_of(self.model)
        if kind is None:
            return super().has_view_permission(request, obj)
        if not super().has_view_permission(request, obj):
            return False
        return allows(actor_from_request(request), f"{kind}.read", obj)

    def has_change_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        """An append-only model is not editable from here, by construction.

        Read off `append_only = True` (house rule 20's declared population)
        rather than off which base class the subclass happened to choose: the
        rule is about the model's promise, and an admin that offered a Save
        button would be offering to break it. Overriding takes a deliberate
        subclass that says so, which is the whole point of making the default
        this way round.
        """
        if is_append_only(self.model):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        """The other half. History that can be deleted is not history."""
        if is_append_only(self.model):
            return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request: HttpRequest, obj: M, form: ModelForm[M], change: bool) -> None:
        actor, tenant = self.acting(request)
        action: Action = "update" if change else "create"
        service = self.service_for(action)
        if service is None:
            self.refuse_unwired(action)
            super().save_model(request, obj, form, change)
            return
        try:
            self.call_service(
                service,
                request=request,
                obj=obj,
                form=form,
                actor=actor,
                tenant=tenant,
                change=change,
            )
        except DomainError as exc:
            self.render_refusal(request, exc)

    def delete_model(self, request: HttpRequest, obj: M) -> None:
        actor, tenant = self.acting(request)
        service = self.service_for("delete")
        if service is None:
            self.refuse_unwired("delete")
            super().delete_model(request, obj)
            return
        try:
            service(tenant=tenant, actor=actor, **{self.object_kwarg: obj})
        except DomainError as exc:
            self.render_refusal(request, exc)

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[M]) -> None:
        """The bulk action, through the same door as the single one.

        Django's default is `queryset.delete()`, which reaches the database
        without passing `delete_model` at all — so the one place house rule 10
        held on the admin was the button nobody uses, and "delete selected" was
        the one that did not. Row by row is slower and is what a staff member
        clicking a checkbox actually meant.

        **The first refusal stops the sweep.** Carrying on would leave the
        selection half applied on a page that says why one row was refused and
        nothing about the rest — a partial outcome nobody chose. Stopping means
        the rows already deleted stay deleted, which is inherent to row-by-row
        and is what the message is for.
        """
        for obj in queryset:
            self.delete_model(request, obj)
            if self.refusal(request) is not None:
                return

    # The keyword a delete service takes the object as. Named rather than
    # guessed, because `delete_widget(widget=...)` and `delete_order(order=...)`
    # are both right and neither is derivable.
    object_kwarg: str = "obj"

    def call_service(
        self,
        service: Any,
        *,
        request: HttpRequest,
        obj: M,
        form: ModelForm[M],
        actor: Actor,
        tenant: Tenant | None,
        change: bool,
    ) -> None:
        """How the form's cleaned data reaches the service.

        Subclasses override this when the mapping is not one-to-one. The
        default passes every changed field as a keyword, which is what a
        `create_x(*, tenant, actor, **fields)` service takes.
        """
        fields = {name: form.cleaned_data[name] for name in form.changed_data}
        if change:
            service(tenant=tenant, actor=actor, **{self.object_kwarg: obj}, **fields)
        else:
            service(tenant=tenant, actor=actor, **fields)


class ReadOnlyModelAdmin[M: Model](ServiceModelAdmin[M]):
    """Visible, searchable, and impossible to change from here.

    For tables whose whole value is that nothing rewrites them.
    """

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        return False


@admin.register(Tenant)
class TenantAdmin(ServiceModelAdmin[Tenant]):
    list_display = ("name", "slug", "status", "timezone", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "slug")
    ordering = ("name",)
    prepopulated_fields: ClassVar[dict[str, Any]] = {"slug": ["name"]}
    # `status` and its timestamps are set by `suspend_tenant` / `close_tenant`
    # and nothing else. A dropdown here would let somebody flip a tenant to
    # "suspended" without the timestamp, the reason or the audit row — three
    # facts an incident review needs and a dropdown cannot supply.
    readonly_fields = ("id", "status", "suspended_at", "closed_at", "created_at", "updated_at")

    def service_for(self, action: Action) -> Any | None:
        from apps.core.services import create_tenant

        # Creation goes through the service, so the "first membership is the
        # owner" rule holds. There is no `rename_tenant` service — the slug is
        # the public handle and is not meant to move — so an edit is Django's,
        # deliberately, and the fields that *do* have services are read-only
        # above.
        return create_tenant if action == "create" else None

    def call_service(self, service: Any, **kwargs: Any) -> None:
        # `actor=actor` is the rider AUDIT-3 carried (ADR core-22). This override
        # exists because `create_tenant` takes neither a `tenant` (it produces
        # one) nor the form's changed fields verbatim — but it used to drop the
        # ACTOR with them, so the one service this class can reach was called by
        # a door that had resolved who was asking and then said nothing. Rule 49
        # cannot see this: it reads signatures, and every signature here was
        # already right; what was wrong was a keyword that was never passed on.
        form = kwargs["form"]
        actor = kwargs["actor"]
        service(name=form.cleaned_data["name"], slug=form.cleaned_data["slug"], actor=actor)


class MoveOrganizationForm(forms.Form):
    """The intermediate page's one question: **where to?**

    A `ModelChoiceField` whose queryset is handed in per request rather than
    declared on the class, because the legal answers are not a property of the
    form — they are a property of who is asking. The class-level default is
    `for_tenant(None)`, which is the tenancy's own fail-closed answer and reads
    as one: a form built without the keyword offers nothing rather than the
    whole table. There is no shape of this file in which "I forgot to scope it"
    should render as "every tenant's tree", and writing the default as
    `.none()` would have said the same thing in a vocabulary house rule 8
    cannot check.
    """

    new_parent = forms.ModelChoiceField(
        queryset=Organization.objects.for_tenant(None),
        label="New parent",
        help_text=(
            "The node this subtree will hang under. Moving a node moves "
            "everything below it, in every org-scoped table, as a durable run."
        ),
    )

    def __init__(self, *args: Any, choices: QuerySet[Organization], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # A string, because `ModelChoiceField[...]` is a stubs-only generic:
        # `cast` evaluates its first argument at runtime and the real class
        # takes no parameter.
        field = cast("forms.ModelChoiceField[Organization]", self.fields["new_parent"])
        field.queryset = choices


@admin.register(Organization)
class OrganizationAdmin(ServiceModelAdmin[Organization]):
    """The tenant's tree, visible and reshaped only through its services.

    `path`, `depth` and `parent` are read-only here on purpose, and **they stay
    read-only now that the move action exists** (ADR core-10). They are the
    hierarchy's load-bearing columns, and a support agent editing `parent` in a
    form would silently orphan a subtree from every `visible_to` in the product
    — the one failure this model exists to make impossible. The action is the
    door; the field is not, and the distinction is the whole design: a form
    write is one `UPDATE` on one row, where a move is an authorization at both
    ends plus a locked, batched, resumable rewrite of every descendant's path.

    Re-parenting is therefore `move_to_new_parent` below, which asks for a
    destination on an intermediate page and calls
    `core.services.move_organization` — the service that authorizes both ends,
    refuses the shapes that are not a move, and starts the durable run.

    **`slug` and `tenant` are read-only for the same reason, and that reason is
    a scar**. `call_service` below hands
    `rename_organization` one field — `name` — so a form that *rendered*
    editable `slug` and `tenant` controls was offering two writes it then threw
    away: the page said Saved, the row did not change, and nothing anywhere
    said no. A screen that offers what the service will not do is worse than a
    screen that offers nothing, because the operator walks away believing the
    edit landed. `tenant` is read-only permanently — moving a node between
    tenants is not a rename, it is a migration of everything below it, and
    there is no service for it. `slug` is read-only **until a rename-slug
    service exists**: it is the org's stable handle, referenced from paths and
    pickers, so re-slugging is a service with its own audit row, not a text
    input. The day that service lands, `slug` comes out of `readonly_fields`
    and into `call_service` **together**, which is the pairing this scar is
    about.
    """

    list_display = ("name", "slug", "tenant", "path", "depth", "created_at")
    list_filter = ("depth",)
    list_select_related = ("tenant", "parent")
    search_fields = ("name", "slug", "path")
    ordering = ("tenant__slug", "path")
    readonly_fields = (
        "id",
        "slug",
        "tenant",
        "path",
        "depth",
        "parent",
        "created_at",
        "updated_at",
    )
    actions = ("move_to_new_parent",)

    #: The intermediate page. Named on the class so a product can restyle it
    #: without reaching into the method that renders it.
    move_template = "admin/core/organization/move_to_new_parent.html"

    def get_queryset(self, request: HttpRequest) -> QuerySet[Organization]:
        return super().get_queryset(request).select_related("tenant", "parent")

    def service_for(self, action: Action) -> Any | None:
        from apps.core.services import rename_organization

        # Only the rename. Creating a node needs a parent chosen against the
        # tree, and moving one is the action below rather than a form field —
        # neither is half-implemented behind a Save button.
        return rename_organization if action == "update" else None

    object_kwarg = "organization"

    def call_service(self, service: Any, **kwargs: Any) -> None:
        form = kwargs["form"]
        service(
            tenant=kwargs["tenant"],
            actor=kwargs["actor"],
            organization=kwargs["obj"],
            name=form.cleaned_data["name"],
        )

    # --- The move: the tree's one human door (ADR core-10) -----------------
    #
    # Before this action there was no `/admin/` path that reached
    # `move_organization` at all — the service was deliberately door-less, and
    # every support move was a shell session. The three-move grammar the
    # service grew (retry, conflict, supersede) had never once been
    # driven by a user-initiated write.
    #
    # What is deliberately NOT here: any second copy of what a legal move is.
    # The choices below are narrowed by *tenancy* — the rows this staff hat can
    # already see on this changelist — and by nothing else. Moving a node under
    # itself, under its own descendant, moving the root, or pushing the subtree
    # past the depth limit are all refused by
    # `core.services._refuse_impossible_move`, and they are refused there for
    # every caller. A dropdown that pre-filtered them would be a second
    # rulebook to keep in step with the first, and a stale second rulebook is a
    # door that quietly forbids what the service allows.

    def move_targets(
        self, request: HttpRequest, organization: Organization
    ) -> QuerySet[Organization]:
        """The destinations this staff member may choose between.

        `get_queryset` and not a fresh `Organization.objects` query: whatever
        narrowing this admin applies to the changelist — `for_tenant` today,
        and `visible_to` the day `Organization` becomes org-scoped — is the
        narrowing the picker must have too. Reading it from one place is what
        keeps "the form shows no foreign tenant's orgs" true by construction
        rather than by a second `for_tenant` somebody has to remember.

        The node itself is dropped because a picker labelled "new parent" that
        offers the row being moved is a broken widget, not a policy — and that
        is the only exclusion here, for the reason the block above gives.
        """
        return self.get_queryset(request).exclude(pk=organization.pk)

    @admin.action(description="Move to a new parent…", permissions=["change"])
    def move_to_new_parent(
        self, request: HttpRequest, queryset: QuerySet[Organization]
    ) -> TemplateResponse | None:
        """Re-parent one subtree, through the service, from the changelist.

        **One node at a time, and that is a property of the question rather
        than a policy**: this page asks for a single destination, and two
        selected nodes do not have one answer — the legal destinations differ
        per node, and a partial sweep would leave half a selection moved above
        a message explaining one refusal (the reasoning `delete_queryset`
        states for its own first-refusal stop).

        Returning `None` hands the request back to Django, which redirects to
        the changelist — where the success line or `render_refusal`'s message
        is waiting. That is the shape `response_change` takes on a refusal, and
        it is what lets the `AuditEntry` commit: a refusal is a return here,
        never an exception climbing out of the view.
        """
        nodes = list(queryset[:2])
        if len(nodes) != 1:
            # `message_user` and not `render_refusal`: a bad *selection* is not a
            # `DomainError` — no service was called and no refusal code names
            # this — so there is nothing for the composed refusal to compose.
            # Reaching for one here would mean minting a refusal code for a
            # screen's own arithmetic, and codes stay a service vocabulary.
            self.message_user(
                request,
                "Select exactly one organization to move: a move asks for one "
                "destination, and every node has its own legal ones.",
                level=messages.ERROR,
            )
            return None

        organization = nodes[0]
        targets = self.move_targets(request, organization)

        if request.POST.get("_move"):
            form = MoveOrganizationForm(request.POST, choices=targets)
            if form.is_valid():
                self.move(request, organization, form.cleaned_data["new_parent"])
                return None
        else:
            form = MoveOrganizationForm(choices=targets)

        context = {
            **self.admin_site.each_context(request),
            "title": f"Move {organization}",
            "opts": self.model._meta,
            "organization": organization,
            "form": form,
            "media": self.media + form.media,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, self.move_template, context)

    def move(
        self, request: HttpRequest, organization: Organization, new_parent: Organization
    ) -> None:
        """Call the service, and say what happened. **The action writes nothing.**

        House rule 10 in its plainest form: this method has no `save()`, no
        `update()` and no knowledge of `path` — it resolves an actor, hands two
        rows to `move_organization` and renders whatever comes back. The
        refusal path is `ServiceModelAdmin.render_refusal`, the composer the
        membership form's refusals already go through, so a `Conflict` from a
        live run and a `Forbidden` from a hat covering only one end read the
        same on the screen as they do on the wire.

        `tenant` comes from the row rather than from `acting()`, as
        `MembershipAdmin.call_service` takes it from the row for the same
        reason: the node was resolved out of `get_queryset`, which is already
        narrowed to the acting tenant, so the row's tenant *is* the acting
        tenant — and it is a `Tenant` rather than a `Tenant | None`.
        """
        from apps.core.services import move_organization

        actor, _ = self.acting(request)
        tenant = organization.tenant
        try:
            move_organization(
                tenant=tenant,
                organization=organization,
                new_parent=new_parent,
                actor=actor,
            )
        except DomainError as exc:
            self.render_refusal(request, exc)
            return
        self.message_user(
            request,
            f"Moving “{organization}” under “{new_parent}”. It is a durable run and "
            f"the subtree lands when it finishes. The run is "
            f"“{self.move_run_id(tenant=tenant, organization=organization)}”.",
            level=messages.SUCCESS,
        )

    def move_run_id(self, *, tenant: Tenant, organization: Organization) -> str:
        """The id of the run the service just started, for the success line.

        Built here through the same bridge callable `move_organization` builds
        it with, from the same four parts, because **`core` may not import
        `apps.workflows`** — the dependency runs the other way, and the bridge
        is how core reaches upward at all (`core.mail` names an id the same
        way). That makes this a second statement of one key, which is a drift
        risk answered the way this repository answers the others: a test
        crosses the app line rule 7 exempts it from and pins the two against
        `apps.workflows.services.workflow_id` itself, so a change to either
        side fails rather than quietly printing an id that names nothing.
        """
        build_id = bridge.get(bridge.WORKFLOW_ID)
        return str(
            build_id(tenant=tenant, app="core", noun="organization", key=str(organization.pk))
        )


@admin.register(Membership)
class MembershipAdmin(ServiceModelAdmin[Membership]):
    """Who belongs where — written through the escalation wall, like every other door.

    Previously this class declared no `service_for`, so `ServiceModelAdmin`
    fell through to `obj.save()` and the admin was the **one** way to grant a
    role without the wall running and without an `AuditEntry`. A support agent
    with an admin login could make an owner, and "who made them an owner, and
    when" had no answer.

    Three services now, and there is no fourth: `add_membership` for a grant,
    `set_role` for a promotion, `revoke_membership` for a withdrawal. **The
    delete was unwired** — `service_for("delete")` returned
    `None` and `refuse_unwired` refused, which was the honest state while
    nothing anywhere removed a membership through a service. What built one is
    a withdrawal that has to run the wall's mirror image (an admin
    may not remove an owner), write its audit row, refuse taking the tenant's
    last owner, and close the person's open sockets — none of which a bare
    `obj.delete()` from this form was ever going to do.

    `tenant` for the delete comes from `acting()`, and that is safe here for the
    reason `get_queryset` gives: this form only ever shows rows inside the
    acting tenant, because the queryset is read through `for_tenant`. A staff
    member who wants another tenant's membership switches with `X-Tenant`,
    which is a thing they did and which the trail records.

    On the change form only `role` is editable, because `set_role` changes only
    the role. Moving a membership to another organization is a re-grant, not an
    edit, and offering a dropdown that silently did nothing would be worse than
    not offering it.
    """

    list_display = ("user", "tenant", "organization", "role", "is_default", "created_at")
    list_filter = ("is_default", "role")
    list_select_related = ("user", "tenant", "organization")
    search_fields = ("user__email", "tenant__name", "tenant__slug", "organization__slug")
    autocomplete_fields = ("user", "tenant", "organization")
    object_kwarg = "membership"

    def get_queryset(self, request: HttpRequest) -> QuerySet[Membership]:
        """Narrowed to the acting tenant **explicitly**, because nothing else does it.

        `Membership` is a `BaseModel` and not a `TenantScopedModel` — it is the
        row that *says* who belongs to a tenant, so it cannot be read through a
        membership — which means it carries an ordinary manager and
        `ServiceModelAdmin.get_queryset`'s scoped branch falls straight through
        to Django's `all()`. The earlier lockdown walled the writes here and could
        not wall this: previously any staff hat opening `/admin/core/membership/`
        read every tenant's membership table, which is the one place "staff act
        across tenants" survived the fix that removed it everywhere else.

        The narrowing is `for_tenant`'s shape written out by hand, and the
        fail-closed half is the point: **no acting tenant reads nothing**, not
        everything, with no superuser exemption — `resolve_tenant` answers
        `None` for a staff member with no membership and for one whose
        `X-Tenant` names a tenant they do not belong to, and both of those are
        people who should be looking at an empty table rather than at all of
        them.

        DOES NOT COVER — declared: the *organization* half. `Membership` is not
        an `OrgScopedModel` (it is what defines the hats `visible_to` reads),
        so a tenant admin still sees their whole tenant's memberships rather
        than their subtree's. House rule 24's second half is about rows a part
        of a tenant owns; who belongs to the tenant is the tenant's.
        """
        rows = super().get_queryset(request).select_related("user", "tenant", "organization")
        tenant = actor_from_request(request).tenant
        if tenant is None:
            return rows.none()
        return rows.filter(tenant=tenant)

    def get_readonly_fields(
        self, request: HttpRequest, obj: Membership | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ()
        return ("user", "tenant", "organization", "is_default")

    def formfield_for_dbfield(self, db_field: Any, request: HttpRequest, **kwargs: Any) -> Any:
        """`role` is a dropdown of the keys this tenant may actually name.

        The column lost its `choices` in `0018` — a role is a key now, and two of
        its three layers (a declared role, a tenant's own `core.Role` row) are
        not knowable from a field definition. Django's default for a plain
        `CharField` is a free-text input, and a free-text input on the one form
        that hands out authority is an invitation to type `admn` and create a
        membership that holds nothing.

        So the choices are assembled per request, from the same three layers
        `add_membership` validates against, and labelled the way a person reads
        them (`role_label`). **It is the convenience and not the guard**: the
        services refuse an unknown key whatever a form posts, and a posted value
        outside this list is a `ChoiceField` validation error — the rendered "Select
        a valid choice" on the form, never a 500 and never a silent write.

        The tenant is the ACTING one, which is also what `get_queryset` narrows
        this changelist to. With no acting tenant there is nothing to read the
        third layer with, and the list is `owner` plus the declared roles —
        which is exactly what a deployment with no custom roles has anyway.
        """
        if db_field.name == "role":
            from apps.core.authz import OWNER_ROLE, role_declarations
            from apps.core.services import known_role_keys, role_label

            tenant = actor_from_request(request).tenant if request is not None else None
            if tenant is None:
                keys = sorted({OWNER_ROLE} | set(role_declarations()))
                labels = [
                    (key, "Owner" if key == OWNER_ROLE else role_declarations()[key].name)
                    for key in keys
                ]
            else:
                labels = [
                    (key, role_label(tenant=tenant, key=key))
                    for key in sorted(known_role_keys(tenant=tenant))
                ]
            # Built rather than passed through: the kwargs the admin hands this
            # hook are shaped for a model field's own `formfield()`, and a
            # `ChoiceField` accepts almost none of them.
            return forms.ChoiceField(
                label="Role",
                choices=labels,
                required=not db_field.blank,
                help_text=db_field.help_text,
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def service_for(self, action: Action) -> Any | None:
        from apps.core.services import add_membership, revoke_membership, set_role

        return {
            "create": add_membership,
            "update": set_role,
            "delete": revoke_membership,
        }.get(action)

    def call_service(self, service: Any, **kwargs: Any) -> None:
        """The form onto the two signatures, which are not the same shape.

        **The granting actor is the request's user**, which is what turns the
        wall on: `_refuse_escalation` measures the granter's own effective role
        over the organization being granted in, and refuses both a grant above
        it and a grant outside their subtree.

        `tenant` comes from the form on a create and from the row on an edit —
        not from `acting()`. It is safe to let the form name one because the
        wall is what decides: a staff member acting in one tenant who names
        another holds no effective role there, and the grant is refused before
        anything is written.
        """
        form = kwargs["form"]
        actor = kwargs["actor"]
        data = form.cleaned_data
        if kwargs["change"]:
            membership: Membership = kwargs["obj"]
            service(
                tenant=membership.tenant,
                membership=membership,
                role=data["role"],
                actor=actor,
            )
            return
        service(
            user=data["user"],
            tenant=data["tenant"],
            organization=data["organization"],
            is_default=bool(data.get("is_default")),
            role=data["role"],
            actor=actor,
        )


@admin.register(Invitation)
class InvitationAdmin(ReadOnlyModelAdmin[Invitation]):
    """Visible, and not editable from here.

    Editing an invitation by hand would mean changing a role or an expiry
    without the audit row that `invite_member` writes — and re-sending one is
    `invite_member` again, which supersedes the old row properly. There is
    nothing left for a form to do.
    """

    list_display = ("email", "tenant", "role", "status", "expires_at", "created_at")
    list_filter = ("status", "role")
    list_select_related = ("tenant", "invited_by")
    search_fields = ("email", "tenant__slug")
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Invitation]:
        return super().get_queryset(request).select_related("tenant", "invited_by")


@admin.register(AuditEntry)
class AuditEntryAdmin(ReadOnlyModelAdmin[AuditEntry]):
    """Read-only, because the model refuses writes and the admin should agree.

    The model would raise `AuditImmutable` anyway; showing a save button that
    always errors is worse than not showing one.
    """

    list_display = ("created_at", "action", "outcome", "door", "actor_kind", "object_type")
    list_filter = ("outcome", "door", "actor_kind", "action")
    list_select_related = ("actor_user", "actor_token", "tenant")
    search_fields = ("action", "object_id", "correlation_id", "request_id", "trace_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[AuditEntry]:
        return super().get_queryset(request).select_related("actor_user", "actor_token", "tenant")
