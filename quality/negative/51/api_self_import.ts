/*
 * THE NEGATIVE THAT WOULD HAVE CAUGHT RDF-1's DEFECT 1.
 *
 * `api` importing `api` is a SELF-IMPORT, which this rule's own statement
 * permits in its first clause ("imports only from its own layer or a layer
 * strictly below it"). `api` being off the ranked chain bounds what may reach
 * IN to it; it says nothing about the layer's internal cohesion.
 *
 * Both shapes are here on purpose, because the defect flagged both: a
 * type-only edge and a runtime value edge. The runner must be silent on each.
 */

import type { Refusal } from "@/api/refusals";
import { registryRefusal } from "@/api/refusals";
import type { paths } from "@/api/generated/schema";

export type TwinPath = keyof paths;

export function twin(refusal: Refusal): Refusal {
    return registryRefusal ? refusal : refusal;
}
