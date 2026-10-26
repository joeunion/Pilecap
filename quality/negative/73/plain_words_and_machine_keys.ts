// Plain English compounds (two hyphenated parts, or a run joined by a small word) must stay silent.
// The compounds here are names nothing in the tree serves, so the plant needs no collision
// declaration and stays honest on a product that renames any URL.
import type { LexiconWord } from "@/copy/lexicon";

export const PLAIN_COPY = {
    socket_closed: {
        detail: "Couldn't connect. Sign in again; an up-to-date follow-up keeps the page.",
    },
} as const;

export const WORD: LexiconWord = "Sign in";
export const LOOKUP = PLAIN_COPY["socket_closed"];
