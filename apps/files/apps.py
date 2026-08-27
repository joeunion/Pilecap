from django.apps import AppConfig


class FilesConfig(AppConfig):
    """**The bytes never come through here, and that is the whole design.**

    A document is two things that age differently: an identity somebody renames,
    files under a purpose and eventually archives, and a pile of bytes that must
    never change once anything has cited its digest. ADR files-2 splits them —
    `StoredFile` owns the first, `FileVersion` owns the second — so that
    "replace this document" is a NEW version finalized and promoted rather than
    an overwrite that rewrites `sha256` and `size_bytes` under every audit row
    and export manifest that already quoted them.

    **Bytes move directly between the client and the object store**, on
    presigned URLs this app mints and audits; nothing streams through Django in
    either direction. That is why `storage.py` exists as its own module rather
    than as a section of `services.py`: it is the one place a bucket is named
    and the one place boto3 is imported, which is what makes "exactly one place"
    a thing a check can see — the same reasoning `apps/accounts/zitadel.py`
    records about the identity platform (house rule 27), and what the storage
    wall (ADR files-2 § "Rules & canaries born with it") will fence.

    `depends_on` names two apps today:

    * `core` — the tenant, the organization tree, `@service`, the scoped
      managers every read here goes through, and `core.log`;
    * `accounts` — `settings.AUTH_USER_MODEL` is the target of `uploaded_by` on
      both models, and the actor an issuance is audited under is a person or a
      token from that app.

    **Three more landed later, each the day something imported it** rather
    than the day somebody planned it:

    * `usage` — `record_stored` meters `files.storage.bytes` through
      `usage.services.record_usage`, inside the finalize transaction, so a
      rolled-back finalize accrues nothing;
    * `events` — `record_stored` emits `files.file.stored`;
    * `workflows` — `confirm_upload` starts `FinalizeUpload` on commit.

    A dependency declared before anything imports it is a permission nobody asked
    for, and rule 7 reads this tuple as a ceiling rather than a plan. **Nothing was
    later added to it**, which is worth saying because the draft expected it to: the
    sweep's `ScheduleDeclaration` is a `core` shape (`apps.core.schedules`) and
    the run it starts is `workflows`' business, and both were already here.

    **There is no `lifecycle.py` here and there should not be one yet**: this app
    owns no third-party table, and both models declare their own lifecycle on
    the class where the person adding the table is already standing (ADR
    core-13). `FileVersion` is `purged` — the abandoned `PENDING` rows
    go on a schedule — and `StoredFile` stays `unbounded` with its two residuals
    named out loud: the OBJECTS, which outlive the archive flag until
    `delete_tenant_objects` lands (ADR files-2 rules object purge out of v1
    deliberately), and the rows an export's own retention sweep leaves behind
    (a known frontier, disposed of in the declaration rather than left for whoever
    finds it). The one population that CANNOT declare on a class is the object
    store itself — an off-ORM keyspace — and it joins through this app's own
    `lifecycle.py::register(registry)` on the day something can reach it.

    **There IS an `integrations.py` here, and it could not have been
    anywhere else.** The integrations census (`apps/core/integrations.py`) asks
    every app whether the external service it owns is real in this deployment;
    An earlier attempt to answer for object storage from `core` was
    refused by house rule 48 by name, because the row's REMEDY has to print the bucket
    setting and rule 48 fences that name to `storage.py` and `config/settings/`.
    So the fact is declared here, live-probed with the same `head_bucket` call
    `/readyz` makes, and the words come from the seam.
    """

    name = "apps.files"
    verbose_name = "Files"
    depends_on: tuple[str, ...] = ("core", "accounts", "events", "usage", "workflows")
