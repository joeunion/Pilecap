/**
 * `SurfaceState` — the total function. A screen is a total function from state
 * to render, and it is not a screen until all four states are authored
 * (fe-conventions §3).
 *
 * FOUR STATES, NEVER FIVE (P16 ruling 2). Transport failure is a member of
 * `error`'s input vocabulary — the discriminated union in `@/api/refusals` —
 * not a state of its own. The four-state census is the closed question every
 * shipped screen already answers, and adding a fifth would reopen it for all of
 * them.
 *
 * The word is `ready`. It is never `populated`, `loaded`, `success` or `data`:
 * one census reads these names, and a screen spelling a fifth word is a screen
 * the census cannot see.
 */

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
export type { Refusal, WireRefusal, WireRemedy } from "@/api/refusals";
export { unhandledRefusal } from "@/api/refusals";

/**
 * What an empty state PROPOSES. The label is the act, in the imperative.
 *
 * An empty state that only reports emptiness has told the person something they
 * could already see.
 */
export type NextAct = { readonly label: string; readonly detail?: string };

export type SurfaceState<TData> =
    | { readonly kind: "loading" }
    | { readonly kind: "empty"; readonly nextAct: NextAct }
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

/** Exhaustiveness, as a compile error rather than as a habit. */
export function unhandledState(state: never): never {
    throw new Error(`unhandled SurfaceState: ${JSON.stringify(state)}`);
}
