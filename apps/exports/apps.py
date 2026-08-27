from django.apps import AppConfig


class ExportsConfig(AppConfig):
    """A tenant can take its data and leave. **The whole app is that sentence.**

    Portability is not a feature a product adds when a customer asks: by then
    the answer is a support engineer with `pg_dump` and a shared bucket, and
    what leaves the deployment is one database's worth of everybody's rows.
    So the export is a door like any other — a service, a durable run, two
    doors, an artifact addressed under the asking tenant's own prefix — and
    what it may read is decided by exactly the predicate every other read in
    this product is decided by (`for_tenant(...).visible_to(...)`).

    `depends_on` names five apps and each is load-bearing:

    * `core` — the tenant, the organization tree, the `@service` decorator and
      the scoped managers the walk reads through. **No longer `core.storage`**:
      XPr retired this app's use of `tenant_prefixed_key`, whose key grammar
      contradicts ADR files-2, and the isolation in the bucket is now the files
      seam's tenant prefix;
    * `files` — **the archive is a document**. `files.services.store_stream`
      files it, `files.storage.presign_get` signs for it and
      `files.storage.delete_object` sweeps it, and `Export.artifact_version`
      points at the `FileVersion` that owns the object. This dependency landed
      the day something imported it, which is the only day a `depends_on` line
      should move;
    * `accounts` — the person who asked (`requested_by`) and
      `policies.administers_the_whole_tenant`, which is the ceiling a
      **tenant-wide** export has to clear. Reusing that predicate rather than
      writing a second one is deliberate: erasure and export are the two acts
      that reach a whole tenant at once, and they must not come to disagree
      about who may;
    * `events` — the request and the completion are published, and this app
      **imports** `emit` rather than inverting through `core.bridge` for the
      reason `apps.comms` gives: the bridge exists so a *lower* layer can call
      a higher one, and a domain app is already above the spine;
    * `workflows` — building an archive is minutes of streaming and it must
      survive a deploy, so it is a Temporal workflow and never a thread.

    There is no `lifecycle.py` here and there should not be one: this app owns
    no third-party table. `Export` declares its own lifecycle on the class,
    which is where a declaration belongs when the model can carry it (ADR
    core-13), and `rules.yaml`'s rule-11 whitelist does not name a
    `lifecycle` module for `exports` for exactly that reason.
    """

    name = "apps.exports"
    verbose_name = "Exports"
    depends_on: tuple[str, ...] = ("core", "accounts", "events", "files", "workflows")
