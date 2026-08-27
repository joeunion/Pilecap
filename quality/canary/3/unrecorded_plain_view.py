

# Planted: the next open door nobody wrote down. A plain Django view at
# the root answers exactly as well without a recorded reason as with one, which
# is why prose in a docstring was never going to hold — four of the six views
# `config/urls.py` mounts outside the API were recorded that way and nothing
# refused a fifth.
#
# Appended rather than written into the list above, so the canary exercises the
# real resolver: `urlpatterns` is already built, `path` and `views` are already
# imported, and this is the shape a rung actually lands.
urlpatterns.append(path("canary-open-view", views.index, name="canary-open-view"))
