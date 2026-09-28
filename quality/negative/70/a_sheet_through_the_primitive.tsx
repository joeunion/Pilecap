import { useRef } from "react";

import { Dialog } from "@/primitives/dialog";

export function Rename({ open, onDismiss }: { readonly open: boolean; readonly onDismiss: () => void }) {
    const form = useRef<HTMLFormElement>(null);
    return (
        <Dialog
            open={open}
            title="Rename the branch"
            onDismiss={onDismiss}
            foot={
                <button type="button" onClick={() => form.current?.requestSubmit()}>
                    Rename
                </button>
            }
        >
            <form ref={form}>
                <p>Close the old name out by giving the branch a new one.</p>
            </form>
        </Dialog>
    );
}
