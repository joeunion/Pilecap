"""A tag, and the link that puts it on a row. Two tables, owned by two scopes.

**`Tag` is TENANT-WIDE** (`TenantScopedModel`). A tag is the tenant's shared
vocabulary — *urgent* means the same thing in every branch — so every member
of the tenant may SEE every tag, and the words are coined, renamed and archived
at the tenant's root (house rule 55: a kind that names no node is asked at a
node the caller resolved). The template's hierarchy has not yet given
tenant-wide kinds a home, so the reads ask at the acting hat under the dated
`hat-scoped` stopgap every other tenant-wide kind carries
(`docs/product/architecture.md`, "asked at a node the caller resolved"). An
org-scoped tag homed at the root was rejected: `visible_to` reads DOWN only, so
a branch member could never see the words they are meant to use.

**`TagLink` is ORG-SCOPED** and lands where its SUBJECT lives. Tagging a row is
an act on that row, so the link belongs to the branch that owns the row: a
sibling branch can neither see the link nor learn that the subject exists.

**The subject is a polymorphic pointer, never a foreign key** — the owner's
ruling for attachments: a template cannot know a product's nouns, and a link
table per noun costs a model, a migration and a set of routes per noun. The
price is declared rather than hidden: the database will not stop an orphan. A
link is read only THROUGH its subject (`?subject=<kind>:<id>` resolves the
subject first), so a pointer whose subject is gone is unreachable rather than
wrong.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import Archivable, OrgScopedModel, TenantScopedModel

#: The word a subject's model lists in its `attachments` declaration to accept
#: tags — `attachments = ("notes", "files", "tags")`. One constant, read by the
#: service that refuses an undeclared kind and by nothing typed anywhere else.
ATTACHMENT = "tags"


class Tag(TenantScopedModel, Archivable):
    """One word in the tenant's vocabulary. Archived, never deleted.

    `slug` is the identity (unique per tenant, archived rows included — an
    archived tag still owns its word, and coining it again is `restore`, not a
    second row); `name` is how a person wrote it. Archiving a tag takes it off
    `/djb_tags/` and out of every picker; the links that already carry it stay
    readable on their subjects, because what was said about a row is not unsaid
    by retiring the word.
    """

    #: The authorization kind, prefixed like the app's label: a platform name a
    #: product never spells, so a product's own `Tag` keeps the kind its class
    #: name derives. The policy keys and the road's url_names follow from it.
    authz_kind: ClassVar[str] = "djb_tag"

    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a tag is a tenant's vocabulary, not its traffic: the population grows with "
            "the words a business coins and never with time, and a retired word is "
            "archived rather than deleted because the links that carry it still say it."
        ),
        trigger=(
            "2026-09-27 — the first tenant whose vocabulary churns (tags coined per "
            "campaign and abandoned), which is the tenant that needs a purge of archived "
            "tags no link names any more."
        ),
    )

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, allow_unicode=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "tag"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["tenant", "slug"], name="djb_tags_tag_slug_per_tenant"),
        ]
        # The inherited recency composite, re-added under this table's name
        # (house rule 37): the base's `%(class)s_recency` would be `tag_recency`,
        # and index names are global to the Postgres schema — a product's own
        # `Tag` already owns that one.
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["tenant", "-created_at"], name="djb_tags_tag_recency"),
        ]

    def __str__(self) -> str:
        return self.name


class TagLink(OrgScopedModel):
    """One tag on one subject row. At most one per `(tag, subject)`.

    `organization` is the SUBJECT's (the landing law): the service reads it off
    the resolved subject and never off the caller's hat, so a link can never
    sit in a branch its own subject is not in.
    """

    #: The authorization kind, prefixed like the app's label: a platform name a
    #: product never spells, so a product's own `TagLink` keeps the kind its class
    #: name derives. The policy keys and the road's url_names follow from it.
    authz_kind: ClassVar[str] = "djb_tag_link"

    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a link lives exactly as long as the fact it records — this row carries that "
            "word — and it is removed by the person who says otherwise; the subject is a "
            "polymorphic pointer, so no cascade can end it when the subject goes."
        ),
        trigger=(
            "2026-09-27 — the first product that HARD-deletes a noun declaring tags, which "
            "is the product that needs a sweep reacting to that noun's deleted event and "
            "removing the links it orphaned."
        ),
    )

    tag = models.ForeignKey(Tag, on_delete=models.PROTECT, related_name="links")
    subject_kind = models.CharField(max_length=64)
    subject_id = models.UUIDField()

    class Meta(OrgScopedModel.Meta):
        verbose_name = "tag link"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["tag", "subject_kind", "subject_id"],
                name="djb_tags_taglink_one_per_subject",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            # The inherited recency composite, re-added: Django does not merge
            # `Meta.indexes` down an inheritance chain (house rule 37). Named
            # for this table, not `%(class)s_recency` — index names are global
            # to the Postgres schema.
            models.Index(fields=["tenant", "-created_at"], name="djb_tags_taglink_recency"),
            # Every read of a link starts at its subject.
            models.Index(
                fields=["tenant", "subject_kind", "subject_id"], name="djb_tags_taglink_subject"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.subject_kind}:{self.subject_id} #{self.tag_id}"

    @property
    def subject(self) -> str:
        """The pointer as the doors spell it — `<kind>:<id>`."""
        return f"{self.subject_kind}:{self.subject_id}"

    @property
    def tag_name(self) -> str:
        return self.tag.name

    @property
    def tag_slug(self) -> str:
        return self.tag.slug
