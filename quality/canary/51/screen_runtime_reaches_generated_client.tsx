/*
 * MANDATED PLANT 1 (generated-types disposition): a RUNTIME import from the
 * generated client module, in a screen, STILL FIRES.
 *
 * This is the half of the two-part predicate that source alone would lose. The
 * clause legalises an ERASED edge to a machine-written module; it says nothing
 * about a screen calling the door. Value bindings survive the bundle, and a
 * screen holding one has resolved its own fetch — fe-conventions Law 2 and Law
 * 4, which is the whole subject of the rule this clause sits on top of.
 *
 * Same module and same layer as the negative beside it; only the erasure
 * differs. That is what makes the predicate two-part rather than a source
 * allow-list wearing a clause's clothes.
 */

import { fetchOrganizations } from "@/api/client";

export function RuntimeReachScreen() {
    return fetchOrganizations ? null : null;
}
