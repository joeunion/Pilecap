import type { NextConfig } from "next";

// THE PROXY, AND THE THREE LINES THAT ARE NOT DEFAULTS. Each one is a defect
// this repository's frontend conventions were written from
// (`.claude/skills/fe-conventions/SKILL.md` §6); none of them announces itself
// when it is wrong, which is why they are pinned here with the argument beside
// them rather than left to a later reader's judgement.
//
// THE ONE PLACE OUTSIDE `src/api/` THAT NAMES THE BACKEND ORIGIN, and it is the
// declared exception to Law 2 rather than a hole in it: a rewrite is where the
// origin is *defined*, so the seam can be same-origin and carry the session
// cookie without a CORS story at all. No component, route or test may name it.
const DJANGO_ORIGIN = process.env.DJANGO_ORIGIN ?? "http://127.0.0.1:8000";

// The version segment is `config/urls.py`'s, and the client takes it verbatim
// rather than composing one (P16 ruling 1: rule 32 translates as CONSUMPTION).
const API_PREFIX = "/api/v1";

const nextConfig: NextConfig = {
    // NEXT 16 WRITES `AGENTS.md` AND `CLAUDE.md` INTO THIS DIRECTORY ON THE
    // FIRST `next dev` UNLESS THIS IS OFF, and in this repository that is not a
    // convenience, it is a second authority file appearing where the first one
    // already says what the rules are. A generated `frontend/CLAUDE.md` would
    // be read by every agent that opens this directory, would say things nobody
    // here decided, and would go stale the moment Next's template changed —
    // which is the exact class `CLAUDE.md` opens by refusing. `README.md` and
    // `.claude/skills/fe-conventions/SKILL.md` are the two files that answer
    // "how do I write anything here", and there are deliberately no others.
    agentRules: false,

    // React 19 StrictMode double-invokes effects in development. It is ON on
    // purpose: the bootstrap that ran twice and the cleanup that discarded the
    // answer (§6.3, §6.4) are only visible with it on, and a template that
    // turned it off would ship every product that mistake pre-hidden.
    reactStrictMode: true,

    // §6.1 — the 308 that ate the request. Next's default answers
    // `/api/v1/organizations/` with a 308 BEFORE any rewrite runs, and a
    // browser following that redirect drops the method and the body. Django's
    // resource paths all end in a slash, so every proxied call would be a
    // redirect pair.
    skipTrailingSlashRedirect: true,

    // §6.6 — the page that rendered perfectly and never hydrated. The page is
    // served through the proxy on a different origin than `next dev` itself;
    // with this unset the development server refuses the hydration assets and
    // refuses them QUIETLY. Both spellings, because to a browser they are two
    // different origins.
    allowedDevOrigins: ["127.0.0.1", "localhost"],

    async rewrites() {
        // §6.2 — the rewrite that ate the slash. The segment form `:path*`
        // splits on `/` and rejoins, silently dropping a trailing empty
        // segment, so `/api/v1/organizations/` arrives at Django as
        // `/api/v1/organizations` and django-ninja answers its own 404. The
        // regex form captures the rest of the path verbatim, slash included.
        return [
            {
                source: `${API_PREFIX}/:path(.*)`,
                destination: `${DJANGO_ORIGIN}${API_PREFIX}/:path`,
            },
        ];
    },
};

export default nextConfig;
