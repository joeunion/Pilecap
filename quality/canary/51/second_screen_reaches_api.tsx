/*
 * A SCREEN REACHING `api` DIRECTLY — and the shape is deliberate twice over.
 *
 * IT PLANTS WHERE SCREENS ACTUALLY LIVE. Real screens are nested one directory
 * down (`screens/welcome/welcome-screen.tsx`), not flat under `screens/`, so a
 * plant at the flat level would prove the rule sees a folder no product uses.
 * This is rule 52's own precedent — its second canary exists to prove the walk
 * DESCENDS rather than to re-prove the defect.
 *
 * IT CARRIES BOTH EDGES THE SEAM CARRIES. The surface-state seam imports the
 * refusal vocabulary as a TYPE and re-exports `unhandledRefusal` as a VALUE,
 * so its crossing is a runtime one and not merely an erasable type edge. Both
 * shapes are reproduced here, one path over from the seam, and both must fire.
 *
 * TODAY that holds `does_not_cover`'s sentence to account: "a `import type`
 * across the boundary is still flagged", which is a claim until something
 * plants it.
 *
 * THE DAY rule 51's one `allow_import` entry lands with the rung that writes
 * the seam, this becomes the ALLOW-LIST'S EDGE-PROVER: same layer, same
 * specifiers, same two shapes, one path over — still firing. Had the exemption
 * been written "type-only imports of the refusal vocabulary are legal", this
 * plant would go silent and the fence would have no edges. Written as ONE
 * PATH, the fence has exactly one gate and this plant is on the other side.
 */

import type { Refusal } from "@/api/refusals";
import { unhandledRefusal } from "@/api/refusals";

export type TwinProps = { readonly refusal: Refusal };

export function WelcomeTwin({ refusal }: TwinProps) {
    return unhandledRefusal ? null : refusal.code;
}
