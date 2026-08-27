

def _canary_emit_literal(*, tenant):
    emit(name="example.widget.zapped", tenant=tenant, payload={})
