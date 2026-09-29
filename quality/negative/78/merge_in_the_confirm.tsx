// patterns: §1
import { Dialog } from "@/primitives/dialog";
import { footAct, type Road } from "@/screens/verbs";

const ROAD: Road = { noun: "widget", seat: "record-acts", verbs: ["merge"] };

// Merge's press in the confirm's foot: the one verb no press undoes, confirmed.
export function MergeConfirm({ onDismiss }: { readonly onDismiss: () => void }) {
    const merge = footAct({ allowed_acts: ["merge"] }, ROAD, "merge");
    return (
        <Dialog open title="Merge these?" onDismiss={onDismiss} foot={<button type="button" {...merge?.attrs}>Merge</button>}>
            <p>One becomes the other.</p>
        </Dialog>
    );
}
