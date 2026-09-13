
// THE ALLOW-LIST'S NEGATIVE — "an allow-list that fires is decoration"
// (rules 33 and 48's own words), planted into the one module
// `scope.allow_import` names.
//
// APPENDED, not created: the seam is a real module with real content, and a
// negative that overwrote it would prove the fence around a file the product
// does not have. The two edges below are THE SAME TWO the third canary plants
// one path over (`screens/welcome/welcome-twin.tsx`) and fires on — the
// refusal vocabulary as a TYPE, and `unhandledRefusal` as a VALUE. Same
// layer, same specifiers, same two shapes: silent here, firing there. That
// pair is the whole claim a chokepoint makes and a syntax valve cannot, since
// the fence is a PATH and not a shape. Had the R-d-3 exemption been written
// "type-only imports of the refusal vocabulary are legal", both sites would
// be silent and the fence would have no edges.
import type { WireRefusal as PlantedSeamRefusal } from "@/api/refusals";
import { unhandledRefusal as plantedSeamUnhandled } from "@/api/refusals";

export function plantedSeamNegative(refusal: PlantedSeamRefusal): never {
    return plantedSeamUnhandled(refusal as never);
}
