#!/usr/bin/env python3
"""Give an epubmerge anthology a table of contents worth opening.

The EpubMerge plugin builds an anthology by dropping each source epub into
its own numbered folder and writing one outer content.opf over the top. It
is faithful to the sources, but it nests a navPoint per page ("page_1",
"page_2", ...) under each episode, so the contents run to over twelve
hundred entries named after nothing. Only the episodes are worth navigating
to, and this drops the rest.

It also leaves each episode's navPoint pointing at the same document as its
own first child. Two entries at one location is what makes a reader announce
the episode, break the page, and only then show it; losing the children
settles that too.

WHAT THIS DOES NOT TOUCH
The spine. Every page stays its own document, which is what keeps each image
with the caption written under it -- collapsing pages into one document per
episode would put a wall of images above a wall of captions. The images are
copied through byte for byte, so this changes navigation only and is safe to
run before deciding anything about image formats.

THE REPEATED TITLE CARD (--drop-repeated-header, off by default)
Each episode's pages all open with the same title-card image, because in the
source that card WAS the header of every page -- around 30% of the height of
every page, on a thousand pages. Removing it from all but the episode's
first page is offered, but it is the artist's own page design, so nothing
here does it unless asked.

The input file is never modified: the result is written to --output, and the
two are reported side by side.

Usage:
    python .scripts/anthology_tidy.py IN.epub -o OUT.epub
    python .scripts/anthology_tidy.py IN.epub -o OUT.epub --drop-repeated-header
    python .scripts/anthology_tidy.py IN.epub --dry-run
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPF_NS = "http://www.idpf.org/2007/opf"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

# A spine entry inside an epubmerge anthology: "<part>/EPUB/page_3.xhtml".
PART_OF_HREF = re.compile(r"^(\d+)/")


def root_opf(zf: zipfile.ZipFile) -> str:
    """The OPF the container points at, rather than the first one found --
    an anthology contains one OPF per merged source as well."""
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    el = container.find(f".//{{{CONTAINER_NS}}}rootfile")
    if el is None or not el.get("full-path"):
        raise SystemExit("container.xml names no rootfile; not an epub?")
    return el.get("full-path")


def spine_hrefs(opf_xml: bytes, base: str) -> list[str]:
    """Spine documents in reading order, as archive paths."""
    opf = ET.fromstring(opf_xml)
    ids = {}
    for item in opf.iter(f"{{{OPF_NS}}}item"):
        if item.get("id") and item.get("href"):
            ids[item.get("id")] = item.get("href")
    out = []
    for ref in opf.iter(f"{{{OPF_NS}}}itemref"):
        href = ids.get(ref.get("idref"))
        if href:
            out.append(base + href if base else href)
    return out


def group_by_part(hrefs: list[str]) -> "OrderedDict[str, list[str]]":
    """Spine documents grouped by the merged source they came from, in
    reading order. Anything outside a numbered folder (the anthology's own
    cover) belongs to no part and is left alone."""
    parts: "OrderedDict[str, list[str]]" = OrderedDict()
    for href in hrefs:
        m = PART_OF_HREF.match(href)
        if m:
            parts.setdefault(m.group(1), []).append(href)
    return parts


def first_image(xhtml: str) -> str | None:
    m = re.search(r"<img\b[^>]*\bsrc=\"([^\"]+)\"", xhtml, re.I)
    return m.group(1) if m else None


def drop_leading_image(xhtml: str, src: str) -> tuple[str, bool]:
    """Remove the leading header image, and the line break that separated it
    from the panel below. Only the first match, and only when it is the
    image expected -- a page whose shape differs is reported and left as it
    is rather than being guessed at."""
    pattern = re.compile(
        r"\s*<img\b[^>]*\bsrc=\"" + re.escape(src) + r"\"[^>]*/>"
        r"(?:\s*<br\b[^>]*/>)?",
        re.I)
    new, n = pattern.subn("", xhtml, count=1)
    return new, bool(n)


def collapse_navmap(ncx_xml: bytes) -> tuple[bytes, int, int]:
    """Drop the per-page navPoints nested under each episode, keeping the
    episodes themselves. Returns the new NCX and (episodes, pages dropped)."""
    ET.register_namespace("", NCX_NS)
    ncx = ET.fromstring(ncx_xml)
    navmap = ncx.find(f"{{{NCX_NS}}}navMap")
    if navmap is None:
        return ncx_xml, 0, 0
    dropped = 0
    tops = list(navmap.findall(f"{{{NCX_NS}}}navPoint"))
    for order, top in enumerate(tops, start=1):
        for child in list(top.findall(f"{{{NCX_NS}}}navPoint")):
            top.remove(child)
            dropped += 1
        # playOrder was numbered across every page; with those gone it would
        # start at 1, 14, 38... which is legal but reads as damage.
        top.set("playOrder", str(order))
    for meta in ncx.iter(f"{{{NCX_NS}}}meta"):
        if meta.get("name") == "dtb:depth":
            meta.set("content", "1")
    body = ET.tostring(ncx, encoding="utf-8", xml_declaration=True)
    return body, len(tops), dropped


def rebuild(src: Path, dest: Path, replacements: dict[str, bytes]) -> None:
    """Copy the archive, substituting the entries that changed.

    mimetype goes first and uncompressed, as the specification requires;
    every other entry keeps the compression it arrived with, so the images
    are not re-encoded on the way through.
    """
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        infos = zin.infolist()
        first = [i for i in infos if i.filename == "mimetype"]
        rest = [i for i in infos if i.filename != "mimetype"]
        for info in first:
            zout.writestr(zipfile.ZipInfo("mimetype", info.date_time),
                          zin.read(info), zipfile.ZIP_STORED)
        for info in rest:
            data = replacements.get(info.filename)
            out = zipfile.ZipInfo(info.filename, info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            zout.writestr(out, zin.read(info) if data is None else data)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("epub", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    ap.add_argument("--drop-repeated-header", action="store_true",
                    help="keep the episode's title card on its first page "
                         "only, instead of on every page")
    ap.add_argument("--keep-toc", action="store_true",
                    help="leave the per-page entries in the contents")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change and write nothing")
    args = ap.parse_args()
    if not args.dry_run and not args.output:
        ap.error("give -o/--output, or --dry-run")

    with zipfile.ZipFile(args.epub) as zf:
        opf_path = root_opf(zf)
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        parts = group_by_part(spine_hrefs(zf.read(opf_path), base))
        if not parts:
            raise SystemExit(f"{args.epub.name}: no merged parts found — this "
                             "does not look like an epubmerge anthology")

        replacements: dict[str, bytes] = {}
        stripped = kept = skipped = 0
        headers = []
        if args.drop_repeated_header:
            for part, pages in parts.items():
                head = first_image(zf.read(pages[0]).decode("utf-8", "replace"))
                headers.append((part, head, len(pages)))
                for href in pages[1:]:            # the first page keeps it
                    xhtml = zf.read(href).decode("utf-8", "replace")
                    if first_image(xhtml) != head:
                        skipped += 1
                        print(f"  ! {href}: leads with "
                              f"{first_image(xhtml)!r}, not the part's "
                              f"{head!r} — left alone")
                        continue
                    new, done = drop_leading_image(xhtml, head)
                    if done:
                        replacements[href] = new.encode("utf-8")
                        stripped += 1
                    else:
                        skipped += 1
                kept += 1

        episodes = dropped = 0
        ncx_name = next((n for n in zf.namelist()
                         if n == base + "toc.ncx" or n.endswith("/toc.ncx")
                         or n == "toc.ncx"), None)
        if not args.keep_toc and ncx_name:
            body, episodes, dropped = collapse_navmap(zf.read(ncx_name))
            if dropped:
                replacements[ncx_name] = body

    print(f"{args.epub.name}: {len(parts)} merged parts, "
          f"{sum(len(p) for p in parts.values())} pages")
    if args.drop_repeated_header:
        print(f"  header image kept on {kept} first pages, "
              f"removed from {stripped} following pages"
              + (f", {skipped} left alone" if skipped else ""))
        for part, head, n in headers[:3]:
            print(f"     part {part}: {head}  (×{n} pages -> ×1)")
        if len(headers) > 3:
            print(f"     ... and {len(headers) - 3} more")
    if not args.keep_toc:
        print(f"  contents: {episodes} episode entries kept, "
              f"{dropped} per-page entries dropped")

    if args.dry_run:
        print("\ndry run — nothing written")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rebuild(args.epub, args.output, replacements)
    before, after = args.epub.stat().st_size, args.output.stat().st_size
    print(f"\nwrote {args.output}")
    print(f"  {before/1e6:,.1f} MB -> {after/1e6:,.1f} MB "
          f"({len(replacements)} entries rewritten)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
