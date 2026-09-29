import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WalkNavigation } from "@/app/example/widgets/walk-navigation";
import { WIDGET_COPY } from "@/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@/screens/state";
import {
    Archived,
    ArchivedLoading,
    Empty,
    Error as Refused,
    BulkPartial,
    HasMore,
    ImportInFlight,
    Loading,
    LongName,
    NothingArchived,
    Ready,
    RefusedBulk,
    RefusedRestore,
    Selected,
} from "@/screens/widget/widget-list.stories";

/** The tab names the page's noun, not the landing it would otherwise inherit. */
export const metadata: Metadata = { title: WIDGET_COPY.title };

/**
 * The four required states, then the extras the list's entries name: §8's
 * *Show more* and a name that must wrap; §20's archived cut, its read, its
 * empty and a refused restore; §7's selection bar and a whole batch refused;
 * §17's band over a batch some rows were refused in; §5's Import at the head
 * and §17's band while a run is in flight.
 */
const WALK = [
    ...REQUIRED_STORY_EXPORTS.map((name) => ({ name, Story: { Loading, Empty, Error: Refused, Ready }[name] })),
    { name: "HasMore", Story: HasMore },
    { name: "LongName", Story: LongName },
    { name: "Archived", Story: Archived },
    { name: "ArchivedLoading", Story: ArchivedLoading },
    { name: "NothingArchived", Story: NothingArchived },
    { name: "RefusedRestore", Story: RefusedRestore },
    { name: "Selected", Story: Selected },
    { name: "RefusedBulk", Story: RefusedBulk },
    { name: "BulkPartial", Story: BulkPartial },
    { name: "ImportInFlight", Story: ImportInFlight },
] as const;

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
            <div data-example="widget-list">
                {WALK.map(({ name, Story }) => (
                    <section key={name} data-story={name}>
                        <Story />
                    </section>
                ))}
            </div>
        </WalkNavigation>
    );
}
