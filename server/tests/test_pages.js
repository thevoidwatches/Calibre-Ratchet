// Exercised from tests/test_pages.py via node.
import { pageLabel } from "../ratchet/static/format.js";

process.stdout.write(JSON.stringify({
  many: pageLabel(312),
  one: pageLabel(1),
  thousands: pageLabel(7950),
  // calibre reports 0 for a book it has never measured, which is "unknown"
  // rather than "no pages" — the row should say nothing at all.
  zero: pageLabel(0),
  missing: pageLabel(undefined),
  null_: pageLabel(null),
  empty: pageLabel(""),
  negative: pageLabel(-5),
  nonsense: pageLabel("lots"),
  numeric_string: pageLabel("204"),
}));
