/*
 * MANDATED PLANT 2 (generated-types disposition): THE EXCLUSION, PROVEN.
 *
 * A type-only import of the REFUSAL vocabulary, direct from the api layer, in a
 * screen. It still fires. The generated-types clause legalises erased edges to
 * the GENERATED client module only, and `api/refusals` is not that module — so
 * the exclusion holds on the SOURCE half of the predicate, whatever the
 * provenance of the name being imported.
 *
 * It is a plant of its own rather than a second line on the edge-prover beside
 * it, because a canary that fires on either of two lines cannot say WHICH edge
 * it caught: if the exclusion broke and only the runtime line still fired, a
 * combined plant would stay green and report nothing. This one carries the
 * type-only edge alone, so its silence would be unambiguous.
 *
 * Why refusal vocabulary is excluded where document shapes are not: wire-error
 * semantics above the client seam are the rule-14 translation's defect whether
 * the import survives the bundle or not — the erasure removes the bundle edge,
 * not the knowledge edge. A screen reads refusals through the surface-state
 * seam (the R-d-3 route), which is one declared module rather than an open set.
 */

import type { Refusal } from "@/api/refusals";

export type DirectRefusalProps = { readonly refusal: Refusal };
