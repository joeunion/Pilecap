// patterns: §1
/**
 * The sheet's own words (patterns.md §1). The primitive knows no product
 * nouns, so it owns only the words every sheet speaks whatever its noun: its
 * one dismiss, which sits in the HEAD and never in the foot (house rule 70),
 * and the in-place ask a sheet with unsaved changes makes before a re-read.
 * Every label is a lexicon row (rule 72).
 */

export const DIALOG_COPY = {
    dismiss: "Close",
    /**
     * The in-place dirty ask (patterns.md §1): a sheet whose form
     * has changes asks before a re-read throws them away. Not a second dialog —
     * it sits in the sheet's body, *Keep editing* first and focused.
     */
    discardQuestion: "Discard your changes?",
    keepEditingAct: "Keep editing",
    discardAct: "Discard",
} as const;
