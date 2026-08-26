"""Pre-flight decision logic. Pure functions; no I/O; fully unit-tested.

The invariant this module enforces:

    FanFicFare is never invoked while any locally-held chapter is absent
    from the site's current chapter list.

Why: FFF's update rebuilds the epub from the site's CURRENT list, reusing
local chapter text by URL match (verified, FFF 4.60.0). Its only guard is a
count comparison, so "50 chapters stubbed + 60 new posted" passes the guard
and silently drops the 50. Comparing chapter *identity sets* instead of counts
closes that hole completely.

Decisions:
  up_to_date      nothing to do (retitles reported informationally)
  update          safe to run fanficfare -u
  refuse_missing  >=1 local chapter no longer on the site — never auto-update
  refuse_non_append  insertions/reorders present and config says refuse
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .epub import Chapter


@dataclass
class Diff:
    local_count: int
    remote_count: int
    new: list[Chapter] = field(default_factory=list)        # on site, not local
    missing: list[Chapter] = field(default_factory=list)    # local, not on site
    retitled: list[dict] = field(default_factory=list)      # same key, new title
    is_clean_append: bool = False   # local sequence is a prefix of remote sequence
    common_reordered: bool = False  # shared chapters appear in a different order


@dataclass
class Decision:
    action: str          # up_to_date | update | refuse_missing | refuse_non_append
    diff: Diff
    reasons: list[str] = field(default_factory=list)

    @property
    def ok_to_update(self) -> bool:
        return self.action == "update"


def compute_diff(local: list[Chapter], remote: list[Chapter]) -> Diff:
    lkeys = [c.key for c in local]
    rkeys = [c.key for c in remote]
    lset, rset = set(lkeys), set(rkeys)

    if len(lset) != len(lkeys) or len(rset) != len(rkeys):
        # Duplicate identity keys would make set logic lie. Should not happen
        # with real FFF data; fail loudly rather than guess.
        raise ValueError("duplicate chapter keys in local or remote list")

    remote_by_key = {c.key: c for c in remote}
    local_by_key = {c.key: c for c in local}

    new = [c for c in remote if c.key not in lset]
    missing = [c for c in local if c.key not in rset]

    retitled = []
    for k in lset & rset:
        lt, rt = local_by_key[k].title, remote_by_key[k].title
        if lt and rt and lt != rt:
            retitled.append({"key": k, "old_title": lt, "new_title": rt})

    is_clean_append = lkeys == rkeys[: len(lkeys)]

    shared_local_order = [k for k in lkeys if k in rset]
    shared_remote_order = [k for k in rkeys if k in lset]
    common_reordered = shared_local_order != shared_remote_order

    return Diff(
        local_count=len(local), remote_count=len(remote),
        new=new, missing=missing, retitled=retitled,
        is_clean_append=is_clean_append, common_reordered=common_reordered,
    )


def decide(local: list[Chapter], remote: list[Chapter],
           non_append_updates: str = "allow") -> Decision:
    d = compute_diff(local, remote)

    if d.missing:
        titles = ", ".join(c.title or c.key for c in d.missing[:8])
        more = "" if len(d.missing) <= 8 else f" (+{len(d.missing) - 8} more)"
        return Decision(
            action="refuse_missing", diff=d,
            reasons=[
                f"{len(d.missing)} local chapter(s) are no longer on the site: "
                f"{titles}{more}.",
                "Updating would drop them from your epub (FanFicFare rebuilds "
                "from the site's current chapter list). This usually means the "
                "story was stubbed. See PLAN.md 'Manual recovery' before doing "
                "anything.",
            ],
        )

    if not d.new:
        reasons = ["No new chapters."]
        if d.retitled:
            reasons.append(
                f"{len(d.retitled)} chapter title(s) changed on the site "
                "(content unchanged locally; run a manual refresh if you care)."
            )
        return Decision(action="up_to_date", diff=d, reasons=reasons)

    if d.is_clean_append:
        return Decision(action="update", diff=d,
                        reasons=[f"{len(d.new)} new chapter(s), clean append."])

    # New chapters exist but were inserted mid-list and/or shared chapters
    # were reordered. FFF handles this correctly (URL-keyed reuse, output in
    # site order) and the post-verify re-checks the result, but it is unusual
    # enough that a config knob can force manual review.
    note = (f"{len(d.new)} new chapter(s) with insertion/reorder "
            f"(not a clean append).")
    if non_append_updates == "allow":
        return Decision(action="update", diff=d, reasons=[note])
    return Decision(
        action="refuse_non_append", diff=d,
        reasons=[note, "fanficfare.non_append_updates is set to 'refuse'."],
    )


def verify_post_update(remote: list[Chapter], post: list[Chapter]) -> list[str]:
    """After fanficfare -u: the epub must now match the site list exactly,
    in order. Returns a list of problems; empty means verified."""
    problems: list[str] = []
    rkeys = [c.key for c in remote]
    pkeys = [c.key for c in post]
    if set(rkeys) - set(pkeys):
        problems.append(f"chapters expected but absent after update: "
                        f"{sorted(set(rkeys) - set(pkeys))[:5]} ...")
    if set(pkeys) - set(rkeys):
        problems.append(f"unexpected chapters present after update: "
                        f"{sorted(set(pkeys) - set(rkeys))[:5]} ...")
    if not problems and pkeys != rkeys:
        problems.append("chapter order does not match the site")
    return problems
