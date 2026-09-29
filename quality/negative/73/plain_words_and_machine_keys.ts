// collides: sign-in — an English compound that is also a URL name; a plain word must stay silent
import type { LexiconWord } from "@/copy/lexicon";

export const PLAIN_COPY = {
    socket_closed: {
        detail: "Couldn't connect. Sign in again; your up-to-date sign-in keeps the page.",
    },
} as const;

export const WORD: LexiconWord = "Sign in";
export const LOOKUP = PLAIN_COPY["socket_closed"];
