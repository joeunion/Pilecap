import { preload } from "react-dom";

export function Downloader({ loaded, href }: { readonly loaded: boolean; readonly href: string }) {
    preload(href, { as: "fetch" });
    const downloader = loaded ? "Saved to your files." : "Reading the file…";
    return <p>{downloader}</p>;
}
