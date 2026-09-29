// patterns: §21
/**
 * THE LEXICON — the product's closed set of labels (patterns.md §21; house
 * rule 72).
 *
 * One word per thing, everywhere. Every label a copy module writes — the value
 * of a `label`, `act`, `title`, `heading` or `dismiss` key, or of a key ending
 * in `Label`, `Act`, `Title` or `Heading` — is a row here, VERBATIM: the case
 * and the punctuation are the word. A rename is one line here, and every copy
 * module still spelling the old word goes red.
 *
 * The rows below are the template's own words, the only ones it owns: the
 * placeholder landing's, the refusal panel's, and the sheet's one dismiss. A
 * product adds its words here, one row each, when its design names them.
 *
 * No row carries a machine token (house rule 73): a label is said to a
 * person, and a person cannot say `invoice_id` back to anybody.
 */

export const LEXICON = [
    "Welcome",
    "Sign in",
    "Sign in to see where you are acting",
    "The server refused",
    "The server did not answer",
    "Couldn't connect",
    "Your access here ended",
    "Close",
    // The noun-verb family (the verb table, `@/screens/verbs`): each verb's
    // pressed word, busy form, state word and refused label. A product renames
    // a verb once, here, product-wide, and never per noun.
    "Edit",
    "Save",
    "Saving…",
    "Couldn't save",
    "Move",
    "Moving…",
    "Moved",
    "Move again",
    "Couldn't move",
    "Duplicate",
    "Duplicating…",
    "Duplicated",
    "Couldn't duplicate",
    "Merge",
    "Merging…",
    "Merged",
    "Couldn't merge",
    "Archive",
    "Archiving…",
    "Archived",
    "Couldn't archive",
    "Restore",
    "Restoring…",
    "Couldn't restore",
    "Import",
    "Checking…",
    "Importing…",
    "Imported",
    "Couldn't import",
    "Add a note",
    "Add a file",
    "Add a tag",
    "Adding…",
    "Couldn't add",
    "Remove tag",
    "History",
    "Couldn't load the history",
    // The family's faces (EXAMPLE, the worked Widget): Edit's reload after a
    // save that lost a race, and the sheet's in-place dirty ask; the
    // selection bar's clear; the bulk band's two ways back; the History card's
    // earlier page.
    "Reload",
    "Keep editing",
    "Discard",
    "Clear the selection",
    "Restore them",
    "Move them back",
    "Show earlier",
    // Attach's cards and its inline field's one press.
    "Notes",
    "Files",
    "Add",
    // The worked Widget face (EXAMPLE): the noun's plural, its fact labels,
    // its two standing-state words and its record's card titles.
    "Widgets",
    "Added",
    "Last changed",
    "Onboarded",
    "Onboarding",
    "About",
    "Details",
    "Show more",
    "Showing more…",
] as const;

export type LexiconWord = (typeof LEXICON)[number];
