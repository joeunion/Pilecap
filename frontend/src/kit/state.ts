// patterns: none — draws no face
/**
 * `SurfaceState` — the total function. A screen is a total function from state
 * to render, and it is not a screen until all four states are authored
 * (fe-conventions §3).
 *
 * FOUR STATES, NEVER FIVE. Transport failure is a member of
 * `error`'s input vocabulary — the discriminated union in `@/api/refusals` —
 * not a state of its own. The four-state census is the closed question every
 * shipped screen already answers, and adding a fifth would reopen it for all of
 * them.
 *
 * The word is `ready`. It is never `populated`, `loaded`, `success` or `data`:
 * one census reads these names, and a screen spelling a fifth word is a screen
 * the census cannot see.
 */

import type { ComponentType } from "react";

import type { Refusal } from "@/api/refusals";

/**
 * THE REFUSAL VOCABULARY REACHES THE SCREENS LAYER THROUGH HERE, AND NOWHERE
 * ELSE (R-d-3, re-ruled 2026-09-02).
 *
 * A screen typed directly against `@/api/refusals` drifts with the wire. That
 * coupling survives `import type`'s erasure — the compile-time erasure removes
 * the bundle edge, not the KNOWLEDGE edge — and it is exactly the defect the
 * rule-14 translation exists to catch (fe-conventions §4, Law 1: HTTP
 * vocabulary never appears above the client seam).
 *
 * So the vocabulary is re-exported from the one module that already legally
 * imports the api layer — this one, because `SurfaceState` names `Refusal` in
 * its own definition below — and screens import it from here.
 *
 * THE TYPES' HOME DOES NOT MOVE. `@/api/refusals` still defines them; these are
 * aliases, not copies, so nothing is re-declared and a fixture typed against
 * `WireRefusal` is still typed against the generated shape (fe-conventions §4
 * Law 3, §6.7).
 *
 * `unhandledRefusal` is a VALUE, not a type, and it is here for the same reason
 * and by the same argument: it is the refusal vocabulary's exhaustiveness
 * helper — the sibling of `unhandledState` below — and leaving it behind would
 * leave a second screens module importing `@/api/refusals`, which is precisely
 * the population this seam exists to reduce to one.
 *
 * THIS IS NOT A BARREL (fe-conventions §2). A barrel re-exports a DIRECTORY and
 * is the shared collision file every parallel rung must edit; this names one
 * module and a closed vocabulary. The ruling's own revisit trigger is written
 * against this line: if the re-export surface grows toward a barrel shape, the
 * rule-51/52 intersection needs its own ruling rather than another entry here.
 */
export type { Refusal, SocketCloseState, WireRefusal, WireRemedy } from "@/api/refusals";
export { REMEDY_DESTINATIONS, unhandledRefusal } from "@/api/refusals";

/**
 * What an empty state PROPOSES. The label is the act, in the imperative.
 *
 * An empty state that only reports emptiness has told the person something they
 * could already see. It is OPTIONAL because a sentence alone is a legal empty
 * (patterns.md §14): when there is nothing to propose (no answer says the hat
 * may create), the surface's copy says what is empty and no act is invented.
 */
export type NextAct = { readonly label: string; readonly detail?: string };

export type SurfaceState<TData> =
    | { readonly kind: "loading" }
    | { readonly kind: "empty"; readonly nextAct?: NextAct }
    | { readonly kind: "error"; readonly refusal: Refusal }
    | { readonly kind: "ready"; readonly data: TData };

/** The runtime census the instruments read. */
export const SURFACE_STATES = ["loading", "empty", "error", "ready"] as const;
export type SurfaceStateKind = (typeof SURFACE_STATES)[number];

/**
 * The four story exports every component story owes, declared BESIDE the states
 * so a lint, a story and a component cannot disagree about what the four are.
 */
export const REQUIRED_STORY_EXPORTS = ["Loading", "Empty", "Error", "Ready"] as const;
export type RequiredStoryExport = (typeof REQUIRED_STORY_EXPORTS)[number];

/**
 * THE STORIES RULE's other half (patterns.md, the preamble): a story module may
 * export MORE than the four only when each extra is named for a state or shape
 * an entry its screen DECLARES (`// patterns: §<n>`) names. This is the one
 * list of those names, per entry; a module declaring none of these entries
 * keeps the four exact, and a fifth export there is as wrong as three.
 */
export const ENTRY_STORY_EXTRAS: Readonly<Record<string, readonly string[]>> = {
    // §1: the family's sheets — Edit's lost race and its other refusal, Move's refusal and its empty,
    // Merge's chooser, its refusal inside the confirm and the confirm's preview refused.
    "§1": ["Stale", "RefusedUpdate", "RefusedMove", "NowhereToMove", "MergeChoosing", "RefusedMerge", "RefusedMergePreview"],
    // §5: the import page's states — checking, previewed, importing, imported, the same file again, a file
    // with no rows, a file refused whole; the list's band while a run is in flight.
    "§5": ["ImportChecking", "ImportPreviewed", "Importing", "Imported", "ImportRepeated", "NothingToImport", "RefusedImport", "ImportInFlight"],
    // §6: the acts row is the row's REST answer — a frame arrives and the acts do not move until the re-read;
    // a one-press act refused in the head's seat.
    "§6": ["ActsAfterFrame", "RefusedDuplicate", "ArrivedAfterMerge"],
    // §7: the selection bar takes the control row's seat; a whole batch refused sits under it.
    "§7": ["Selected", "RefusedBulk"],
    // §8: Show more closes a page that has more; a name with no break wraps inside the row.
    "§8": ["HasMore", "LongName"],
    // §10: the History card — read, being read, empty, refused; the attach cards — read on both hats,
    // being read, empty, an add refused.
    "§10": ["History", "HistoryLoading", "HistoryEmpty", "RefusedHistory", "Attached", "AttachedMember", "AttachLoading", "NothingAttached", "RefusedAttach"],
    // §16: the resting state wears no pill.
    "§16": ["Resting"],
    // §17: a band — the moved-away record's, a batch's that some rows were refused in, the copy's, the merged row's.
    "§17": ["Moved", "BulkPartial", "Duplicated", "Merged"],
    // §20: the archive road — the two hats, the archived state, its two refusals, the cut being read and empty.
    "§20": ["PopulatedAdmin", "PopulatedMember", "Archived", "RefusedArchive", "RefusedRestore", "ArchivedLoading", "NothingArchived"],
};

/** One story a walk page draws: its export name, the story, whether it is walked ALONE, and the door its refusal answers. */
export type WalkedStory = { readonly name: string; readonly Story: ComponentType; readonly alone: boolean; readonly door: string | null };

/**
 * The stories a walk page draws from one stories module, read off the module's exports.
 *
 * The population is the module's own exports, filtered by the names the
 * stories rule admits — the four, then every entry's extras, in that order —
 * so a story added to the module is walked without a page knowing its name,
 * and a page carries no second list. A story that must be walked alone (it
 * opens a modal sheet, or lands focus as it renders) says so on itself:
 * `Story.alone = true`, beside the story, never in a list of the page's.
 * A story whose refusal is another door's answer than the page's own operation names it the same way: `Story.door = "<x-url-name>"`.
 */
// road: story_walk — The stories a walk page draws, read off one stories module's exports. · example: frontend/src/app/example/widgets/import/page.tsx::WidgetImportExamplePage
export function walkOf(stories: Readonly<Record<string, unknown>>): readonly WalkedStory[] {
    const admitted = new Set<string>([...REQUIRED_STORY_EXPORTS, ...Object.values(ENTRY_STORY_EXTRAS).flat()]);
    return [...admitted].flatMap((name) => {
        const Story = stories[name];
        if (typeof Story !== "function") return [];
        const marks = Story as { readonly alone?: unknown; readonly door?: unknown };
        return [{ name, Story: Story as ComponentType, alone: marks.alone === true, door: typeof marks.door === "string" ? marks.door : null }];
    });
}

/** Exhaustiveness, as a compile error rather than as a habit. */
export function unhandledState(state: never): never {
    throw new Error(`unhandled SurfaceState: ${JSON.stringify(state)}`);
}
