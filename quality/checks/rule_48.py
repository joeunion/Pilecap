"""Rule 48: one door to the object store (ADR files-2, P7 Q-32)."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 48: one door to the object store (ADR files-2, P7 Q-32) -------------
#
# The third fence of the rule-27 shape, and the one with the widest blast
# radius. Zitadel's is about a CREDENTIAL and a transaction boundary; the search
# index's (rule 33) is about a WALL. This one is about BYTES: an object store is
# a flat key space with no tenancy in it at all, so the only thing standing
# between one customer's document and another's is the KEY GRAMMAR
# (`apps/files/storage.py::version_key` — `t/<tenant pk>/f/<file pk>/v/<n>`) and
# the belt that refuses a key outside the caller's own prefix
# (`refuse_foreign_key`). Both live in one module, and both are only true while
# that module is the only way to reach a bucket.
#
# FOUR CLAUSES, because there are four ways to open a second door, and only the
# first of them needs the AWS SDK:
#
# 1. **the client**: `boto3`/`botocore` imported by anything under `apps/` that
# is neither the seam nor the readiness probe.
# 2. **the address, the bucket and the credential**: `AWS_STORAGE_BUCKET_NAME`,
# `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`, `AWS_S3_CUSTOM_DOMAIN`,
# `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, named outside the seam and
# outside `config/settings/`, where the environment is read.
# 3. **signing**, and 4. **reading an object's bytes**: `generate_presigned_url`
# / `generate_presigned_post`, `get_object` / `download_fileobj` /
# `download_file`. These are the belt for a module handed a client it did not
# build — no import, no setting, and a signed URL for any key it likes.
#
# AND THE FIFTH DOOR, which is the one that was actually walked through:
# `django.core.files.storage`. `config/settings/base.py` points `STORAGES`
# "default" at `storages.backends.s3.S3Storage` the moment a bucket is named, so
# `default_storage.open()` reads an object's bytes and `default_storage.url()`
# signs a URL — the same two clauses, reached with no boto3 import and no
# setting named anywhere. `apps/exports` wrote its archives exactly that way
# until it was re-pointed onto `files.services.store_bytes`, and its key
# grammar (`tenants/<slug>/<uuid>-<name>`) was a key built out of two renamable,
# user-supplied things. This clause is what stops it coming back.
#
# WHAT F1 LEFT, and why this is a rule now: `apps/files/tests/test_storage_fence.py`
# is the census the wall is written against — a hand-pinned set of the modules
# that import the SDK, so a second importer is a line somebody reads. It covers
# clause 1 and only clause 1: a module that names the bucket, signs a URL, reads
# an object or takes the Django storage door passes it in silence. That pin stays
# (it is the app's own doorbell and it fails by NAME); this rule is the other
# four clauses, planted canaries and all.
#
# Every clause is read from the AST rather than the text, which is what makes
# the negatives possible: this module's prose names `AWS_STORAGE_BUCKET_NAME`
# and boto3 repeatedly — it has to, to explain the fence.

# : The names that may not travel: the bucket, the address, the credential.
# : Deliberately NOT here — `AWS_DEFAULT_ACL`, `AWS_QUERYSTRING_AUTH`,
# : `AWS_QUERYSTRING_EXPIRE`, `AWS_S3_FILE_OVERWRITE` — which configure
# : django-storages' behaviour and dial nothing. Naming one is configuration in
# : the wrong file, not a second door, and refusing it would be the rule growing
# : past its reason (rule 33 stays silent on `MEILI_ENV` for the same reason).
STORAGE_SETTINGS = (
    "AWS_STORAGE_BUCKET_NAME",
    "AWS_S3_ENDPOINT_URL",
    "AWS_S3_REGION_NAME",
    "AWS_S3_CUSTOM_DOMAIN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

# : The client libraries the fence exists to confine.
STORAGE_PACKAGES = ("boto3", "botocore")

# : Django's own storage API — the fifth door, and the one this tree has actually
# : used. An import of it under `apps/` is a caller reaching `default_storage`,
# : which `STORAGES` points at the same bucket.
DJANGO_STORAGE_MODULE = "django.core.files.storage"

# : Signing a URL. Both are boto3 client method names and neither collides with
# : the seam's own public API (`presign_get`, `presign_put`).
SIGNING_METHODS = ("generate_presigned_url", "generate_presigned_post")

# : Reading an object's bytes. Also boto3's own names. `delete_object` is
# : deliberately absent: it is ALSO the name of the seam's own public function
# : (`apps/files/storage.py::delete_object`, which `apps/exports/services.py`
# : calls), so a recogniser holding it would fire on the legal door.
OBJECT_READ_METHODS = ("get_object", "download_fileobj", "download_file")

# : The seam's OWN content read, `apps/files/storage.py::iter_object` — the one
# : server-side read of an object's bytes the seam offers, and it offers it to an
# : ACTIVITY's parser (an import reading a CSV row by row). Called from a door it
# : streams a stored document's bytes through Django to a caller, which is the
# : shape the whole seam exists to prevent. Its own name, so it is NOT in
# : `OBJECT_READ_METHODS`: that tuple fires anywhere outside the seam, and this
# : call is legal from an activity; it fires from a door file only, by bare name
# : or attribute (`from apps.files.storage import iter_object`).
SEAM_CONTENT_READS = ("iter_object",)
_CONTENT_READ_DOORS = frozenset({"api.py", "mcp.py", "consumers.py"})

# : The module every other module must go through, and never around.
SEAM_MODULE = "apps.files.storage"
SEAM_REL = SEAM_MODULE.replace(".", "/") + ".py"
STORAGE_KLASS = "storage_client"


def _names_storage_setting(node: ast.AST) -> str | None:
    """Which fenced name this node names, or `None`. **Never prose.**

    The three shapes and exactly three, as rule 33 has them:
    `settings.AWS_STORAGE_BUCKET_NAME` (an attribute), a string constant that IS
    the name (`os.environ["AWS_STORAGE_BUCKET_NAME"]`), and a bare binding,
    which is how a settings module declares one. A docstring that mentions the
    variable is a `Constant` whose value is the whole docstring, so EQUALITY —
    rather than membership — is what keeps this silent on documentation.
    """
    if isinstance(node, ast.Attribute) and node.attr in STORAGE_SETTINGS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in STORAGE_SETTINGS:
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in STORAGE_SETTINGS else None
    return None


def _imports_any(node: ast.AST, packages: tuple[str, ...]) -> bool:
    """Whether this statement pulls in one of these packages, in either form."""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return any(module == p or module.startswith(f"{p}.") for p in packages)
    if isinstance(node, ast.Import):
        return any(
            alias.name == p or alias.name.startswith(f"{p}.")
            for alias in node.names
            for p in packages
        )
    return False


def _calls_method(node: ast.AST, names: tuple[str, ...]) -> str | None:
    """The fenced method this call calls on something, or `None`.

    Attribute calls only: `client.generate_presigned_url(...)`. A bare
    `get_object(...)` is a module-level function somebody defined here and is
    not the SDK — the whole point of the clause is a client handed in from
    elsewhere, and a client is always a receiver.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr if node.func.attr in names else None
    return None


def _calls_by_name(node: ast.AST, names: tuple[str, ...]) -> str | None:
    """The fenced seam function this node reaches, or `None`.

    A call by bare name or as an attribute (`storage.iter_object(...)`), or the
    import that binds it under any alias (`from apps.files.storage import
    iter_object as read`) — an aliased bare call names nothing a recogniser can
    read, so the import is where it is caught.
    """
    if isinstance(node, ast.ImportFrom) and node.module == SEAM_MODULE:
        for alias in node.names:
            if alias.name in names:
                return alias.name
        return None
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = _callee_name(func)
    return name if name in names else None


def storage_client(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scope = rule.get("scope") or {}
    importers = [str(e.get("path", "")) for e in scope.get("allow_import") or [] if e.get("path")]
    readers = [str(e.get("path", "")) for e in scope.get("allow_secret") or [] if e.get("path")]

    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        is_seam = rel == SEAM_REL
        if is_seam:
            # The module the rule funnels everything into. Its own client, its
            # own settings, its own signing and its own object read are the
            # POINT, and they are counted so that a recogniser which stopped
            # recognising anything trips a floor rather than reporting a clean
            # nothing.
            out.count("seam_module")
        may_import = is_seam or any(rel == e or rel.startswith(e) for e in importers)
        may_read = is_seam or any(rel == e or rel.startswith(e) for e in readers)

        for node in ast.walk(tree):
            named = _names_storage_setting(node)
            if named:
                if may_read:
                    out.count("secret_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"names {named} — the bucket, the address and the credential are read "
                        f"in {SEAM_REL} and declared in config/settings, and nowhere else. An "
                        "object store is a flat key space with no tenancy in it: the only "
                        "thing between one tenant's bytes and another's is the key grammar in "
                        "that module and the prefix belt beside it. Call apps.files.services, "
                        "or add this module to rule 48's allow-list in quality/rules.yaml "
                        "with the reason — which makes this MODULE a standing second "
                        "reader, where `# rule-48: <reason>` on this line exempts this "
                        "line and is counted and printed on every run",
                        klass=STORAGE_KLASS,
                    )
                continue
            if _imports_any(node, STORAGE_PACKAGES):
                if may_import:
                    out.count("sdk_imports")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"imports the AWS SDK — the object store is reached through {SEAM_REL} "
                        "and nowhere else. A client here is a second key space with no grammar "
                        "on it: `version_key` and `refuse_foreign_key` are what keep one "
                        "tenant's bytes out of another's reach, and a client that never met "
                        "them can address any key in the bucket. Call apps.files.services, or "
                        "add this module to rule 48's allow-list in quality/rules.yaml with "
                        "the reason — which makes this MODULE a standing importer, where "
                        "`# rule-48: <reason>` on this import line exempts this line and is "
                        "counted and printed on every run",
                        klass=STORAGE_KLASS,
                    )
                continue
            if _imports_any(node, (DJANGO_STORAGE_MODULE,)):
                if may_import:
                    out.count("storage_api_imports")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"imports {DJANGO_STORAGE_MODULE} — `STORAGES` points `default_storage` "
                        "at the same bucket the moment one is named, so `.open()` reads an "
                        "object's bytes and `.url()` signs a URL with no boto3 import and no "
                        "setting named anywhere. This is the door apps/exports took once, "
                        "under a key built from a renamable slug and a user-supplied filename. "
                        f"Call apps.files.services, or add this module to rule 48's allow-list "
                        "in quality/rules.yaml with the reason — which makes this MODULE a "
                        "standing importer, where `# rule-48: <reason>` on this import line "
                        "exempts this line and is counted and printed on every run",
                        klass=STORAGE_KLASS,
                    )
                continue
            method = _calls_method(node, SIGNING_METHODS)
            if method:
                if may_import:
                    out.count("signing_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"calls {method}() — signing is issuance, and issuance is audited in "
                        f"{SEAM_REL} behind a service that knows whose key it is. A module "
                        "handed a client can sign for any key in the bucket without importing "
                        "anything or naming a setting, which is why the method name is fenced "
                        "as well as the import. Call apps.files.services",
                        klass=STORAGE_KLASS,
                    )
                continue
            if Path(rel).name in _CONTENT_READ_DOORS and not may_import:
                read = _calls_by_name(node, SEAM_CONTENT_READS)
                if read:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"reaches {read}() from a door — the seam's content read is an "
                        "activity's parser's, never a door's: from here a stored document's "
                        "bytes travel through Django to a caller, which is what "
                        f"{SEAM_REL}'s presigned URLs exist to prevent. Issue a download "
                        "URL (apps.files.services), or read it in an activity",
                        klass=STORAGE_KLASS,
                    )
                    continue
            method = _calls_method(node, OBJECT_READ_METHODS)
            if method:
                if may_import:
                    out.count("object_reads")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"calls {method}() — reading an object's bytes outside {SEAM_REL} is a "
                        "read with no prefix belt in front of it (`refuse_foreign_key`), and "
                        "bytes travelling through Django is the one shape apps/files is built "
                        "to prevent. Call apps.files.services",
                        klass=STORAGE_KLASS,
                    )
    return out


from quality.checks.rule_36 import _callee_name  # noqa: E402
