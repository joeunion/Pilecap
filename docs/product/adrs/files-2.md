# ADR files-2

**ADR files-2 (ING-1D design pair, owner-directed; supersedes
files-1's body — files-1's stack ruling stands ratified, and its two-phase
upload, `store_bytes` seam, archive-not-delete, tenant-settings policy and
wall posture all survive intact below) · context:** every product needs
object storage with the walls already built (a first consuming product: issued documents,
papers, template artifacts, digests of "the bytes *we stored*"), file
handling is the single most leak-prone surface a product improvises, and
the owner ruled versioning into v1: "replace this document" is a
first-class act, and a platform that models a file as one mutable blob
answers it with an overwrite — history destroyed, audit orphaned, and a
presigned URL whose meaning changes after issuance. **decision:**
`apps/files` with a two-model aggregate — `StoredFile` (the document:
identity, name, purpose, the walls) owning `FileVersion` rows (the bytes:
one **immutable object key per version**, digest, size, its own two-phase
lifecycle) — bytes never transit Django (presigned URLs both directions,
TTLs declared in settings), every issuance an audited service call,
"replace" = a new version finalized and promoted, never an overwrite;
stored bytes counted on ING-5's ledger at finalize. **rejected:** a
`version` column mutated in place on one row (replace rewrites
digest/size under every audit row and export manifest that cited them —
D9's exact target, applied to bytes); latest-pointer object keys and S3
bucket-versioning as the mechanism (both reasoned below);
`FileField`/media on domain models, public buckets or ACLs in any
configuration, and a generic-FK attachments framework (files-1's
rejections, all standing — the domain owns the edge: a product model
points at `StoredFile` with `PROTECT`, never the reverse). **trigger to
revisit:** direct-to-browser multipart uploads > 5 GB → S3 multipart
presigning grows inside `apps/files/storage.py`, same seam, per-part URLs
under the same wall.
