"""Generate directory-index routes from the maintained public sample pages."""

from pathlib import Path


LANDING = Path(__file__).resolve().parents[1] / "landing"
SLUGS = ("acme-toolkit", "pixelboard", "quantify")


def generated_routes() -> dict[Path, str]:
    routes = {}
    for slug in SLUGS:
        source = (LANDING / "samples" / f"{slug}.html").read_text()
        # The directory index is one path segment deeper than the maintained
        # .html page. Keep every existing relative destination at its original
        # public resource while pointing sample-to-sample links at sibling dirs.
        page = source.replace('href="../', 'href="../../')
        for target in SLUGS:
            page = page.replace(f'href="{target}"', f'href="../{target}/"')
        routes[LANDING / "samples" / slug / "index.html"] = page
    return routes


def main() -> None:
    for destination, contents in generated_routes().items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents)


if __name__ == "__main__":
    main()
