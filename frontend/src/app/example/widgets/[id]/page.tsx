// golden: face begin
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WIDGET_COPY } from "@/copy/widget";
import { walkOf } from "@pilecap/ui/state";
import * as stories from "@/screens/widget/widget-record.stories";

/** The tab names the page's noun, not the landing it would otherwise inherit. */
export const metadata: Metadata = { title: WIDGET_COPY.title };

/** Every story the record's stories module exports, read off the module (`walkOf`): the four, then each entry's extras. */
const WALK = walkOf(stories);

type SearchParams = Readonly<Record<string, string | readonly string[] | undefined>>;

/**
 * EXAMPLE — THE WORKED WIDGET RECORD, WALKED. Development only, `/states`'
 * pattern: in a production build this route is a 404.
 *
 * It renders the record screen's stories whatever the id, because the walk is
 * of the screen's states, not of one row: the list walk's rows land here, and
 * so does any id typed by hand. `data-story` labels each section for the
 * rendered drive; `Ready` is the populated case.
 *
 * A story that opens a sheet — a MODAL dialog — as it renders (§1's, the merge
 * chooser and its confirm among them), or lands focus as it renders, is marked
 * `alone` on itself: two modals on one page make everything but the last one
 * inert. So it is walked one at a time, `?story=<name>`, alone on the page; the
 * default walk draws every other story, and a sheet there opens from the admin
 * story's *Edit* and *Move*.
 */
export default async function WidgetRecordExamplePage({ searchParams }: { readonly searchParams?: Promise<SearchParams> }) {
    if (process.env.NODE_ENV === "production") {
        notFound();
    }
    const asked = (await searchParams)?.story;
    const alone = WALK.find((story) => story.alone && story.name === asked);
    const walk = alone === undefined ? WALK.filter((story) => !story.alone) : [alone];

    return (
        <div data-example="widget-record">
            {walk.map(({ name, Story }) => (
                <section key={name} data-story={name}>
                    <Story />
                </section>
            ))}
        </div>
    );
}
// golden: face end
