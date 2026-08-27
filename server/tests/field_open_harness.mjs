// Which metadata editors start open, and how a stored preference overrides it.
import { localStorageStore } from "./dom_stub.mjs";
const { fieldIsOpen } = await import("../ratchet/static/detail.js");

const results = {
  // Nothing stored: reading list open, the other two closed.
  default_readinglist: fieldIsOpen("#readinglist"),
  default_genre: fieldIsOpen("#genre"),
  default_tags: fieldIsOpen("tags"),
};

localStorageStore.set("ratchet_field_open_#readinglist", "0");
localStorageStore.set("ratchet_field_open_tags", "1");
results.stored_closes_readinglist = fieldIsOpen("#readinglist");
results.stored_opens_tags = fieldIsOpen("tags");
results.unstored_still_default = fieldIsOpen("#genre");

process.stdout.write(JSON.stringify(results));
