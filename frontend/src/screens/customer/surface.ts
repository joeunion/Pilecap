// golden: portal begin
// patterns: none — draws no face
/**
 * The key of the surface this face is drawn for: `apps/example_portal/surfaces.py`
 * declares it, and the route table's rows for these pages carry it in their
 * `surfaces` column. A door this face draws to another page is read from the
 * rows of THIS surface (`pathFor(…, CUSTOMER_SURFACE)`), never the first row
 * that happens to draw the operation.
 */
export const CUSTOMER_SURFACE = "customer";
// golden: portal end
