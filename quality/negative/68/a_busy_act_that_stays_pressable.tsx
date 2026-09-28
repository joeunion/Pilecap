export function Save({ busy, onSave }: { readonly busy: boolean; readonly onSave: () => void }) {
    return (
        <button type="button" aria-busy={busy} onClick={onSave}>
            {busy ? "Saving…" : "Save"}
        </button>
    );
}
