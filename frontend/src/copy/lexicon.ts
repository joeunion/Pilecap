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
] as const;

export type LexiconWord = (typeof LEXICON)[number];
