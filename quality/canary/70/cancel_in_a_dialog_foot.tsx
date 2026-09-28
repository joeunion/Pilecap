import { Dialog } from "@/primitives/dialog";

export function Rename({ open, onDismiss }: { readonly open: boolean; readonly onDismiss: () => void }) {
    return (
        <Dialog
            open={open}
            title="Rename the branch"
            onDismiss={onDismiss}
            foot={
                <>
                    <button type="button" onClick={onDismiss}>
                        Cancel
                    </button>
                    <button type="button">Rename</button>
                </>
            }
        >
            <p>The new name.</p>
        </Dialog>
    );
}
