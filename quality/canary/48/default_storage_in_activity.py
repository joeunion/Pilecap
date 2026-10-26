

# planted violation: THE FIFTH DOOR — Django's own storage API. `STORAGES`
# points `default_storage` at the same bucket the moment one is named, so
# `.open()` reads an object's bytes and `.url()` signs a URL, with no boto3
# import and no setting named anywhere. This is the door `apps/exports` once
# took, under a key built from a renamable slug and a user-supplied filename,
# before its bytes moved onto the files seam.
from django.core.files.storage import default_storage as _canary_default_storage  # planted violation
