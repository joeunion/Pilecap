// A disabled provider signs nobody in; this comment is prose.
const WHY = "A disabled provider signs nobody in: configure a new one.";

export function Why({ wasDisabledBy }: { readonly wasDisabledBy: string }) {
    return (
        <p title={wasDisabledBy}>
            {WHY}
        </p>
    );
}
