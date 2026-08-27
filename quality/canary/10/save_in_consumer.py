

def _canary_save_in_consumer(widget):  # planted violation (rule 10)
    widget.name = "renamed over the socket"
    widget.save()
