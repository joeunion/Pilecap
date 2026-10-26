// golden: face begin
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WalkBoard, WalkNavigation } from "@/app/example/widgets/walk-navigation";
import { WIDGET_COPY } from "@/copy/widget";
import { walkOf } from "@pilecap/ui/state";
import * as stories from "@/screens/widget/widget-list.stories";

/** The tab names the page's noun, not the landing it would otherwise inherit. */
export const metadata: Metadata = { title: WIDGET_COPY.title };

/** Every story the list's stories module exports, read off the module (`walkOf`): the four, then each entry's extras. */
const WALK = walkOf(stories);

/**
 * EXAMPLE — THE WORKED WIDGET LIST, WALKED. Development only, `/states`' pattern:
 * in a production build this route is a 404, so a product that clones the
 * template ships no page nobody meant to publish.
 *
 * It renders the list screen's four stories in the real application, with the
 * real tokens, so every state can be seen and photographed without a world
 * seeded to produce it. `data-story` labels each section for the rendered drive.
 * `Ready` is the populated case; its rows are doors to `/example/widgets/[id]`.
 * Every story is pressable: the chip, *Show more*, a cut row's *Restore*, the
 * checkboxes and the selection bar's verbs are answered from the stories'
 * fixtures, so the walk reads the next page, the other cut and a batch's
 * answer without a server.
 */
export default function WidgetListExamplePage() {
    if (process.env.NODE_ENV === "production") {
        notFound();
    }

    return (
        <WalkNavigation>
            <WalkBoard>
                <div data-example="widget-list">
                    {WALK.map(({ name, Story }) => (
                        <section key={name} data-story={name}>
                            <Story />
                        </section>
                    ))}
                </div>
            </WalkBoard>
        </WalkNavigation>
    );
}
// golden: face end
