

# negative: the RIGHT way to say something to somebody. Importing the comms
# service is not importing a mail module and must never read as one — this is
# the shape the rule is trying to produce, so a false positive here would push
# people back to the shape it is trying to stop.
from apps.comms.services import send as _negative_comms_send
