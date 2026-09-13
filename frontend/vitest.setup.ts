import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// The component tier is NECESSARY AND NEVER SUFFICIENT (fe-conventions §8):
// jsdom has no proxy, no hydration, no double-mount against a real network and
// no origin model. Five defects once shipped on a tree with 574 passing
// component tests. The browser drive is part of a frontend rung, not a later
// stage.
afterEach(() => {
    cleanup();
});
