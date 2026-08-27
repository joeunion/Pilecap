# Planted: the form that was live on four apps until URL-1 — an api module that
# names ITSELF in the URL, so every route it serves asks the caller to learn
# which module of ours happens to hold the thing. There is no failure mode: the
# routes answer exactly as well as they would at a resource-first path, which is
# why a census is the instrument and a code review is not.
#
# `events` is chosen because it is an installed app label that is NOT in rule
# 32's valve — an infrastructure name, never a resource — so the refusal here is
# the real one and not a coincidence.

PREFIX = "events"
