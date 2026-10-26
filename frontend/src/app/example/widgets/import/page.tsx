// golden: import begin
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { importPageTitle } from "@/copy/widget";
import { walkOf } from "@pilecap/ui/state";
import * as stories from "@/screens/widget/widget-import.stories";

/** The tab names the page's act and noun. */
export const metadata: Metadata = { title: importPageTitle() };

/** Every story the import page's stories module exports, read off the module (`walkOf`): the four, then each entry's extras. */
const WALK = walkOf(stories);

/**
 * EXAMPLE — THE WORKED WIDGET IMPORT PAGE, WALKED. Development only, `/states`'
 * pattern: in a production build this route is a 404. Every state of the page
 * is drawn from the stories, each pressable against a stand-in route; the page
 * fetches nothing. `data-story` labels each section for the rendered drive.
 */
export default function WidgetImportExamplePage() {
    if (process.env.NODE_ENV === "production") {
        notFound();
    }
    return (
        <div data-example="widget-import">
            {WALK.map(({ name, Story }) => (
                <section key={name} data-story={name}>
                    <Story />
                </section>
            ))}
        </div>
    );
}
// golden: import end
