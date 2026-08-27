
# The excepted reader, planted in the tree the exception names. Naming a
# variable in order to read it OUT OF THE ENVIRONMENT is not the leak this
# guards — it is the one place the environment is supposed to be read, and a
# rule that refused it would leave the engine with no legal way to be
# configured at all.
MEILI_URL = "http://127.0.0.1:7700"
MEILI_MASTER_KEY = ""  # pragma: allowlist secret
