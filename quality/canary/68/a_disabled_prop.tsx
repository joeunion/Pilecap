export function Save({ busy }: { readonly busy: boolean }) {
    return (
        <button type="button" disabled={busy}>
            Save
        </button>
    );
}
