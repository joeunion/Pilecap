import { Dialog } from "@/primitives/dialog";

const SHEET_COPY = { done: "Finished" } as const;

export function Review({ open, onDismiss }: { readonly open: boolean; readonly onDismiss: () => void }) {
    return (
        <Dialog open={open} title="Review" onDismiss={onDismiss} foot={<button type="button">{SHEET_COPY.done}</button>}>
            <p>Read it through.</p>
        </Dialog>
    );
}
