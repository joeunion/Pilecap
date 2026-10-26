"""`python -m quality.sdk`: the partition (`--census`), the promise (`--surface`, `--ratchet`)."""

import sys

from quality.sdk import census, changelog, reference, surface

argv = sys.argv[1:]
if "--changelog" in argv:
    sys.exit(changelog.main(argv))
if "--reference" in argv:
    sys.exit(reference.main(argv))
sys.exit((surface if {"--surface", "--ratchet"} & set(argv) else census).main(argv))
