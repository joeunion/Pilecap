// golden: face begin
// patterns: none — draws no face
// golden: face end
/**
 * EXAMPLE — the worked Widget face's road: the seat its family acts sit in and
 * the verbs it draws, declared ONCE (`@/screens/verbs` constructs every act
 * from it and the row's `allowed_acts`).
 *
 * A road never names a verb the wire does not serve, and it names every verb
 * door the wire serves for its noun (house rule 77 compares the two, both
 * ways): each verb joins this list in the rung that lands its act on the face.
 * *Edit* (the versioned save), *Move*, *Duplicate*, *Merge* (the chooser, then
 * the one confirm), *Archive* last in `record-acts` and its
 * way back, *Restore* (the archived record's band and the archived cut's rows —
 * never `record-acts`), *Import* at the list head and its page, the attach
 * cards and the tag row, and the History
 * card; the selection bar's verbs are
 * the bulk door's.
 */

// golden: face begin
import type { Road } from "@/screens/verbs";

export const ROAD: Road = {
    noun: "widget",
    seat: "record-acts",
    verbs: [
        // golden: face end
        // golden: version begin
        "update",
        // golden: version end
        // golden: move begin
        "move",
        // golden: move end
        // golden: duplicate begin
        "duplicate",
        // golden: duplicate end
        // golden: merge begin
        "merge",
        // golden: merge end
        // golden: archive begin
        "archive",
        "restore",
        // golden: archive end
        // golden: import begin
        "import",
        // golden: import end
        // golden: attach begin
        "attach",
        // golden: attach end
        // golden: history begin
        "history",
        // golden: history end
        // golden: face begin
    ],
    bulk: [
        // golden: face end
        // golden: bulk begin
        "archive",
        "restore",
        "move",
        // golden: bulk end
        // golden: face begin
    ],
};
// golden: face end
