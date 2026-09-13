import { notFound } from "next/navigation";

import { REQUIRED_STORY_EXPORTS } from "@/screens/state";
import { Empty, Error as Refused, Loading, Ready } from "@/screens/welcome/welcome-screen.stories";

/**
 * THE STATE WALK — the instrument, not a product surface.
 *
 * fe-conventions §8 requires a SCREENSHOT PER AUTHORED `SurfaceState`, in a real
 * browser, on every route a rung touched: four states authored and one
 * screenshotted is one state proven. Two of the four are not reachable against
 * a seeded world on this operation — a signed-in session's organization tree
 * always contains the hat it is acting as, so `empty` cannot be produced by
 * seeding, and `loading` is over in milliseconds — and a state that cannot be
 * photographed cannot be accepted by an owner looking at pictures.
 *
 * So this route renders the four stories, in the real application, with the
 * real tokens and the real screen. It is **development only**: in a production
 * build it is a 404, so a product that clones this template does not ship a
 * page nobody meant to publish. It is also the only route in this tree that is
 * not part of the journey, and it exists because the alternative is a report
 * that describes rendered evidence instead of carrying it.
 */
export default function StatesPage() {
    if (process.env.NODE_ENV === "production") {
        notFound();
    }

    const stories = [Loading, Empty, Refused, Ready] as const;

    return (
        <>
            {stories.map((Story, index) => (
                <section key={REQUIRED_STORY_EXPORTS[index]} data-story={REQUIRED_STORY_EXPORTS[index]}>
                    <Story />
                </section>
            ))}
        </>
    );
}
