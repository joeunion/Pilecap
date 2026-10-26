#!/usr/bin/env bash
# Legal: a stub that writes a fake script; the heredoc's text is not the function's body.
set -euo pipefail

zzz_write_stub() {
    cat > "$1" <<'STUB'
#!/usr/bin/env bash
echo "!! stub: refusing on purpose"
exit 2
STUB
    chmod +x "$1"
}
