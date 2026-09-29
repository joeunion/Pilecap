// patterns: §1
import { Dialog } from "@/primitives/dialog";

// A one-press verb guarded by the dialog primitive: Archive is undone in one
// press, so a confirm here trains the click-through that fires on merge.
export function ArchiveConfirm({ onDismiss }: { readonly onDismiss: () => void }) {
    return (
        <Dialog open title="Are you sure?" onDismiss={onDismiss} foot={<button type="button">Archive</button>}>
            <p>It leaves the book.</p>
        </Dialog>
    );
}
