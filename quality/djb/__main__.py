"""`python -m quality.djb`: `gate <argv>` is the gate; any other first word is `cli`'s."""

import sys

from quality.djb.modes import main

sys.exit(main())
