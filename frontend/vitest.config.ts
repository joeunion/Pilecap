import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": fileURLToPath(new URL("./src", import.meta.url)),
            "@pilecap/ui": fileURLToPath(new URL("./src/kit", import.meta.url)),
            "@pilecap/copy": fileURLToPath(new URL("./src/copy", import.meta.url)),
        },
    },
    test: {
        globals: true,
        environment: "jsdom",
        setupFiles: ["./vitest.setup.ts"],
        include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
        // FILE PARALLELISM OFF, AND IT IS A CORRECTNESS SETTING, NOT A
        // PERFORMANCE ONE (fe-conventions §9). A suite that plants files into
        // the real tree — a lint canary, a boundary fixture — sees another
        // suite's plants when the two run beside each other. This tree has no
        // planting suite YET; the setting ships with the argument attached so
        // that the first one does not arrive into a runner someone has already
        // turned back on for the speed.
        fileParallelism: false,
    },
});
