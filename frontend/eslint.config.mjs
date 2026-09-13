import next from "eslint-config-next";
import nextTypeScript from "eslint-config-next/typescript";

/**
 * `--max-warnings=0` is set in `package.json`, not here, because a warning
 * nobody is required to fix is a rule that has been turned off slowly.
 */
const config = [
    {
        ignores: [".next/**", "node_modules/**", "next-env.d.ts", "src/api/generated/**"],
    },
    ...next,
    ...nextTypeScript,
];

export default config;
