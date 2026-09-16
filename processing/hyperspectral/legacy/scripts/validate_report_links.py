"""Check references in every bundled HTML report, including single-quoted URLs."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import argparse


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("src", "href") and value:
                self.urls.add(value)


def check_report_links(root: Path) -> tuple[int, int]:
    root = root.resolve()
    pages = sorted(root.rglob("*.html"))
    assert pages, f"No HTML reports found in {root}"
    missing = []
    count = 0
    for page in pages:
        parser = References()
        parser.feed(page.read_text(encoding="utf-8"))
        for reference in sorted(parser.urls):
            url = urlsplit(reference)
            if url.scheme or url.netloc or not url.path:
                continue
            path = unquote(url.path)
            target = root / path.lstrip("/") if path.startswith("/") else page.parent / path
            count += 1
            if not target.is_file():
                missing.append(f"{page.relative_to(root)} -> {reference}")
    assert not missing, "Missing report references:\n" + "\n".join(missing)
    return len(pages), count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("results/20260828_showcase"))
    pages, references = check_report_links(parser.parse_args().root)
    print(f"REPORT_LINKS_OK: {pages} HTML reports; {references} local references; none missing")
