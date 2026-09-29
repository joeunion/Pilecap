import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { importPageTitle } from "@/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@/screens/state";
import {
    Empty,
    Error as Refused,
    ImportChecking,
    Imported,
    Importing,
    ImportPreviewed,
    ImportRepeated,
    Loading,
    NothingToImport,
    Ready,
    RefusedImport,
} from "@/screens/widget/widget-import.stories";

/** The tab names the page's act and noun. */
export const metadata: Metadata = { title: importPageTitle() };

/** The four required states, then the page's own: checking, previewed, importing, imported, the same file again, a file with no rows, a file refused whole. */
const WALK = [
    ...REQUIRED_STORY_EXPORTS.map((name) => ({ name, Story: { Loading, Empty, Error: Refused, Ready }[name] })),
    { name: "ImportChecking", Story: ImportChecking },
    { name: "ImportPreviewed", Story: ImportPreviewed },
    { name: "Importing", Story: Importing },
    { name: "Imported", Story: Imported },
    { name: "ImportRepeated", Story: ImportRepeated },
    { name: "NothingToImport", Story: NothingToImport },
    { name: "RefusedImport", Story: RefusedImport },
] as const;

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
