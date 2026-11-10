"""
spec_query.py — Pure query layer over the spec graph (FR-0005, H2).

FR-0003 and FR-0004 gave every spec object a lifecycle (`lifecycle` on FR/TR,
`status` on DEC/ADR), a revision history (`revisions`, `last_breaking_revision`)
and supersession links. This module is the one place that *reads* them and
answers "what is live?", so the indexer, the compiled-slice pipeline (H1),
dashboards (H7) and the integrity gates (WS4) all get the same answer.

Same shape as `spec_footprint.py`: no I/O, no subprocesses, no logging, and no
import of the hyphenated `index-specs.py`. Everything is duck-typed on the
`FR` / `TR` / `DEC` / `ADR` dataclasses the indexer produces — any object with
the same attribute names works, which keeps unit tests trivial.

Surfaces:

1. `visibility(obj)` — exactly one of four classes (`live`, `draft`,
   `superseded`, `rejected`) for any FR / TR / DEC / ADR.
2. `select(objs, include=frozenset())` — the default view (`live` + `draft`,
   minus pre-breaking DECs) with explicit opt-ins `superseded`, `rejected`,
   `history`, `all`.
3. `revision_window(obj, decs_by_id)` / `dec_window_class(dec, objs_by_id)` —
   the "since `last_breaking_revision`" rule (ADR-0001 rule 8).
4. `slice(graph, root_id, mode)` — the reachable subgraph rooted at an FR or
   TR: the H1 seam. Everything reached but not included is recorded in
   `Slice.excluded` so slice-miss diagnostics can be logged.
5. `provisional(decs, as_of)` — provisional DECs classified `past` /
   `pending` / `event` against a caller-supplied date.

Visibility classes (normative table from FR-0005):

    | Class        | FR / TR `lifecycle`  | DEC `status`             | ADR `status`                       |
    |--------------|----------------------|--------------------------|------------------------------------|
    | `live`       | `live` (default)     | `proposed`, `ratified`   | `proposed`, `accepted`, absent/unknown |
    | `draft`      | `draft`              | —                        | —                                  |
    | `superseded` | `superseded`         | `superseded`             | `superseded`, `deprecated`         |
    | `rejected`   | —                    | `rejected`               | `rejected`                         |

The default view is `live` ∪ `draft`: drafts are present-tense work in flight;
H2's target is hiding the *past*. A malformed object is never hidden because it
is malformed — unknown values fall to `live` (the conservative direction is to
show more, not less; the indexer's lint is the fix signal).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, NamedTuple

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

VISIBILITY_CLASSES: tuple[str, ...] = ("live", "draft", "superseded", "rejected")
DEFAULT_VIEW: frozenset[str] = frozenset({"live", "draft"})
INCLUDE_OPTIONS: frozenset[str] = frozenset({"superseded", "rejected", "history", "all"})
SLICE_MODES: tuple[str, ...] = ("current", "migration")
OBJECT_TYPES: tuple[str, ...] = ("FR", "TR", "DEC", "ADR")

_LIFECYCLE_CLASS: Mapping[str, str] = {
    "live": "live",
    "draft": "draft",
    "superseded": "superseded",
}
_DEC_STATUS_CLASS: Mapping[str, str] = {
    "proposed": "live",
    "ratified": "live",
    "superseded": "superseded",
    "rejected": "rejected",
}
_ADR_STATUS_CLASS: Mapping[str, str] = {
    "proposed": "live",
    "accepted": "live",
    "superseded": "superseded",
    "deprecated": "superseded",
    "rejected": "rejected",
}

_ADR_PREFIX = re.compile(r"^(ADR-\d{4})")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TYPE_ORDER = {t: i for i, t in enumerate(OBJECT_TYPES)}


# ---------------------------------------------------------------------------
# Visibility (@implements FR-0005:AC-1)
# ---------------------------------------------------------------------------


def object_type(obj: Any) -> str:
    """`FR`, `TR`, `DEC` or `ADR`, from the object's ID prefix. Falls back to
    the attribute shape (a `lifecycle` carrier is an FR-like object, a
    `status` carrier a DEC-like one) so duck-typed test doubles work."""
    obj_id = str(getattr(obj, "id", "") or "")
    for kind in OBJECT_TYPES:
        if obj_id.startswith(f"{kind}-"):
            return kind
    if hasattr(obj, "lifecycle"):
        return "FR"
    if hasattr(obj, "status"):
        return "DEC"
    return "ADR"


def visibility(obj: Any) -> str:
    """Exactly one of `live`, `draft`, `superseded`, `rejected` for any FR,
    TR, DEC or ADR (see the table in the module docstring). Agrees with
    FR-0003's `is_live` for FR/TR and FR-0004's `is_live_dec` for DECs:
    `visibility(x) == "live"` iff the predicate is true. An absent or
    out-of-enum value is `live` — a malformed object is never hidden because
    it is malformed. @implements FR-0005:AC-1"""
    kind = object_type(obj)
    if kind in ("FR", "TR"):
        lifecycle = getattr(obj, "lifecycle", None)
        if lifecycle is None:
            return "live"
        return _LIFECYCLE_CLASS.get(str(lifecycle), "live")
    status = getattr(obj, "status", None)
    if status is None:
        return "live"
    table = _DEC_STATUS_CLASS if kind == "DEC" else _ADR_STATUS_CLASS
    return table.get(str(status), "live")


def is_default_class(obj: Any) -> bool:
    """True when the object's class is in the default view (`live` or
    `draft`). Ignores revision windows — see `in_default_view` for the full
    rule that also hides pre-breaking DECs."""
    return visibility(obj) in DEFAULT_VIEW


# ---------------------------------------------------------------------------
# Revision window (@implements FR-0005:AC-3)
# ---------------------------------------------------------------------------


def _is_current_position(position: int, last_breaking_revision: int | None) -> bool:
    """Per FR-0004's arithmetic the DEC at 1-based `position` produced
    `version position + 1`. It is current iff that version is at or after the
    recorded `last_breaking_revision` — the breaking DEC itself is current (it
    defines the contract in force). A null marker makes every DEC current."""
    if last_breaking_revision is None:
        return True
    return position + 1 >= last_breaking_revision


def revision_window(
    obj: Any, decs_by_id: Mapping[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    """Split `obj.revisions` (DEC IDs, oldest first) into `(current, history)`
    by position against the *recorded* `last_breaking_revision` — never a
    recomputation from `breaking` flags; when the two disagree FR-0004's lint
    has already warned. Order within each list is the order in `revisions`.

    `decs_by_id` is accepted for call-site symmetry with `dec_window_class`
    and reserved for future use; the split is positional and does not need
    the DEC objects. A DEC that `revises` this object but is absent from
    `revisions` is not part of any window — `dec_window_class` classifies it
    (current, with a note). @implements FR-0005:AC-3"""
    revisions = [str(r) for r in (getattr(obj, "revisions", None) or [])]
    marker = getattr(obj, "last_breaking_revision", None)
    current: list[str] = []
    history: list[str] = []
    for position, dec_id in enumerate(revisions, start=1):
        (current if _is_current_position(position, marker) else history).append(dec_id)
    return current, history


def dec_window_class(dec: Any, objs_by_id: Mapping[str, Any]) -> tuple[str, str | None]:
    """Classify one DEC as `("current", None)` or `("history", None)` by its
    position in its `revises` target's `revisions`. A DEC that cannot be placed
    — `revises: null` (a creating DEC), an unresolved target, or a target whose
    `revisions` does not list it (a reciprocity gap FR-0004 warns on) — is
    `("current", <note>)`: the conservative direction is to show more, and the
    lint line is the signal to fix it. @implements FR-0005:AC-3"""
    dec_id = str(getattr(dec, "id", ""))
    target_id = getattr(dec, "revises", None)
    if target_id is None:
        return "current", f"{dec_id}: revises is null (creating DEC); treated as current"
    target = objs_by_id.get(str(target_id))
    if target is None:
        return (
            "current",
            f"{dec_id}: revises {target_id}, which is not in the graph; treated as current",
        )
    revisions = [str(r) for r in (getattr(target, "revisions", None) or [])]
    if dec_id not in revisions:
        return (
            "current",
            f"{dec_id}: revises {target_id} but {target_id}.revisions does not list it; "
            "treated as current",
        )
    position = revisions.index(dec_id) + 1
    marker = getattr(target, "last_breaking_revision", None)
    return ("current" if _is_current_position(position, marker) else "history"), None


def pre_breaking_reason(dec: Any, objs_by_id: Mapping[str, Any]) -> str | None:
    """For a pre-breaking DEC, the human `Why` wording INDEX.md uses:
    `pre-breaking (<target> v<p+1> < v<last_breaking_revision>)`. None when
    the DEC is current."""
    window, _ = dec_window_class(dec, objs_by_id)
    if window != "history":
        return None
    target = objs_by_id[str(dec.revises)]
    position = [str(r) for r in target.revisions].index(str(dec.id)) + 1
    return f"pre-breaking ({target.id} v{position + 1} < v{target.last_breaking_revision})"


# ---------------------------------------------------------------------------
# Default view and selection (@implements FR-0005:AC-2)
# ---------------------------------------------------------------------------


def _objects_by_id(objs: Iterable[Any]) -> dict[str, Any]:
    return {str(o.id): o for o in objs if getattr(o, "id", None)}


def in_default_view(obj: Any, objs_by_id: Mapping[str, Any] | None = None) -> bool:
    """The default-view predicate: class `live` or `draft`, and — for a DEC —
    in its target's current revision window. `objs_by_id` (FR/TR by ID) is
    needed to place DECs; without it a DEC is placed by class alone (every
    DEC is then current, the conservative reading)."""
    if not is_default_class(obj):
        return False
    if object_type(obj) == "DEC" and objs_by_id is not None:
        window, _ = dec_window_class(obj, objs_by_id)
        return window == "current"
    return True


def normalise_include(include: Iterable[str] | None) -> frozenset[str]:
    """Validate an opt-in set; any value outside `INCLUDE_OPTIONS` is a
    `ValueError` naming it. @implements FR-0005:AC-2"""
    values = frozenset(str(v) for v in (include or ()))
    bad = sorted(values - INCLUDE_OPTIONS)
    if bad:
        raise ValueError(
            f"unknown include value(s) {bad}; expected a subset of {sorted(INCLUDE_OPTIONS)}"
        )
    return values


def select(
    objs: Iterable[Any],
    include: Iterable[str] | None = frozenset(),
    objs_by_id: Mapping[str, Any] | None = None,
) -> list[Any]:
    """Return, in ID order, the objects visible under the default view plus
    the requested opt-ins:

    - empty `include` — exactly the `live` and `draft` objects, minus
      pre-breaking DECs (class wins over window: a current-window DEC that is
      `rejected` or `superseded` stays hidden without its opt-in);
    - `superseded` / `rejected` — adds that class;
    - `history` — adds pre-breaking DECs;
    - `all` — everything.

    The sets compose. `objs_by_id` (FR/TR by ID) places DECs in their
    windows; when omitted it is built from `objs` itself, so passing the whole
    graph's objects just works. @implements FR-0005:AC-2"""
    wanted = normalise_include(include)
    objs = list(objs)
    if objs_by_id is None:
        objs_by_id = _objects_by_id(o for o in objs if object_type(o) in ("FR", "TR"))
    out: list[Any] = []
    for obj in sorted(objs, key=lambda o: str(o.id)):
        if "all" in wanted:
            out.append(obj)
            continue
        cls = visibility(obj)
        if cls in DEFAULT_VIEW:
            if object_type(obj) == "DEC":
                window, _ = dec_window_class(obj, objs_by_id)
                if window == "current" or "history" in wanted:
                    out.append(obj)
            else:
                out.append(obj)
        elif cls in wanted:
            out.append(obj)
    return out


# ---------------------------------------------------------------------------
# Slice — the reachable subgraph (@implements FR-0005:AC-4, AC-5, AC-6)
# ---------------------------------------------------------------------------


class Excluded(NamedTuple):
    """An object reached along a followed edge but not included: `(id, class,
    via)`. Compares equal to a plain 3-tuple."""

    id: str
    visibility: str
    via: str


@dataclass(frozen=True)
class SliceObject:
    """One included object with the class it carried and the edge that reached
    it (`root` for the root itself)."""

    id: str
    type: str
    visibility: str
    via: str
    obj: Any


@dataclass
class Slice:
    root: str
    mode: str
    objects: list[SliceObject] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [o.id for o in self.objects]

    def get(self, obj_id: str) -> SliceObject | None:
        for o in self.objects:
            if o.id == obj_id:
                return o
        return None

    def __contains__(self, obj_id: object) -> bool:
        return any(o.id == obj_id for o in self.objects)


def _sort_key(obj_id: str) -> tuple[int, str]:
    kind = obj_id.split("-", 1)[0]
    return _TYPE_ORDER.get(kind, len(_TYPE_ORDER)), obj_id


def adr_refs_of(dec: Any) -> list[tuple[str, str]]:
    """The ADR IDs a DEC cites: every `authorised_by` entry, plus the
    `ADR-nnnn` prefix of `invokes_exception`. Returns `(adr_id, via)` pairs
    in a deterministic order."""
    refs: list[tuple[str, str]] = []
    for adr_id in getattr(dec, "authorised_by", None) or []:
        refs.append((str(adr_id), "authorised_by"))
    exc = getattr(dec, "invokes_exception", None)
    if exc:
        m = _ADR_PREFIX.match(str(exc))
        if m:
            refs.append((m.group(1), "invokes_exception"))
    return refs


def slice(graph: Any, root_id: str, mode: str = "current") -> Slice:  # noqa: A001
    """The reachable subgraph rooted at an FR or TR — the H1 seam.

    `graph` is anything with `frs`, `trs`, `decs`, `adrs` lists (the indexer's
    `SpecGraph`). The root may be any FR or TR of any class (asking for it by
    ID is the explicit request; a `superseded` root is returned with that
    class). A DEC or ADR root is a `ValueError`; an ID not in the graph is a
    `KeyError`; a `mode` outside `current` / `migration` is a `ValueError`.

    Edges followed, in this order (FR-0005 "Reachable subgraph"):

    1. one object-to-object hop from the root — TR root: `operationalises`
       → FR; FR root: reverse `operationalises` → TR, `extends` and
       `depends_on` → FR; each included only when in the default view;
       in `migration` mode also the root's `supersedes` / `superseded_by`
       neighbour, **any class**;
    2. for every FR/TR now in the set: the DECs in its current revision window
       (`revisions` since `last_breaking_revision`), plus any DEC that
       `revises` it without being listed (treated as current, with a note);
       included when in the default view — pre-breaking, `superseded` and
       `rejected` DECs are excluded;
    3. for every DEC in the set: `constrained_by` → FR (default view);
    4. for every DEC in the set: `authorised_by` and the `ADR-nnnn` prefix of
       `invokes_exception` → ADR (default view; an unresolved ADR is a note,
       never an error).

    Not followed: `supersedes` / `superseded_by` in `current` mode;
    `revisions` outside the window; `satisfies`, `goal`, `success_criteria`;
    `implemented_by`, `tests`; `derived_from`, `pattern`. Every object reached
    but not included lands in `excluded` as `(id, class, via)`. Result order is
    by type (FR, TR, DEC, ADR) then ID; two calls on the same graph are equal.
    @implements FR-0005:AC-4, FR-0005:AC-5, FR-0005:AC-6"""
    if mode not in SLICE_MODES:
        raise ValueError(f"unknown slice mode {mode!r}; expected one of {list(SLICE_MODES)}")
    frs = list(getattr(graph, "frs", []) or [])
    trs = list(getattr(graph, "trs", []) or [])
    decs = list(getattr(graph, "decs", []) or [])
    adrs = list(getattr(graph, "adrs", []) or [])
    frs_by_id = _objects_by_id(frs)
    trs_by_id = _objects_by_id(trs)
    decs_by_id = _objects_by_id(decs)
    adrs_by_id = _objects_by_id(adrs)
    objs_by_id = {**frs_by_id, **trs_by_id}

    root_id = str(root_id)
    if root_id in decs_by_id or root_id in adrs_by_id:
        raise ValueError(
            f"{root_id} is a {object_type(decs_by_id.get(root_id) or adrs_by_id[root_id])}; "
            "a slice root must be an FR or TR"
        )
    if root_id not in objs_by_id:
        raise KeyError(f"{root_id} is not in the spec graph")
    root = objs_by_id[root_id]
    root_kind = object_type(root)

    result = Slice(root=root_id, mode=mode)
    included: dict[str, SliceObject] = {}
    excluded: list[Excluded] = []
    notes: list[str] = []

    def consider(obj: Any, via: str, *, any_class: bool = False) -> bool:
        """Include `obj` (once) when it is in the default view — or
        unconditionally with `any_class` — else record the exclusion."""
        obj_id = str(obj.id)
        if obj_id in included:
            return True
        cls = visibility(obj)
        if any_class or cls in DEFAULT_VIEW:
            included[obj_id] = SliceObject(
                id=obj_id, type=object_type(obj), visibility=cls, via=via, obj=obj
            )
            return True
        excluded.append(Excluded(obj_id, cls, via))
        return False

    # Root, of any class.
    consider(root, "root", any_class=True)

    # 1. One object-to-object hop from the root.
    if root_kind == "TR":
        for fr_id in getattr(root, "operationalises", None) or []:
            fr = frs_by_id.get(str(fr_id))
            if fr is not None:
                consider(fr, "operationalises")
    else:
        for tr in sorted(trs, key=lambda t: str(t.id)):
            if root_id in [str(x) for x in (getattr(tr, "operationalises", None) or [])]:
                consider(tr, "reverse operationalises")
        for key in ("extends", "depends_on"):
            for fr_id in getattr(root, key, None) or []:
                fr = frs_by_id.get(str(fr_id))
                if fr is not None:
                    consider(fr, key)

    if mode == "migration":
        neighbours = 0
        for key in ("supersedes", "superseded_by"):
            ref = getattr(root, key, None)
            if ref is None:
                continue
            neighbour = objs_by_id.get(str(ref))
            if neighbour is None:
                notes.append(f"{root_id}: {key} {ref} is not in the graph")
                continue
            neighbours += 1
            consider(neighbour, key, any_class=True)
        if neighbours == 0:
            notes.append(
                f"{root_id}: supersedes is null and superseded_by is null; "
                "migration mode adds nothing beyond current mode"
            )

    # 2. DEC windows for every FR/TR in the set (snapshot: DECs never add FR/TRs
    #    here; `constrained_by` FRs are one hop further and get no window).
    for obj_id in sorted(included, key=_sort_key):
        entry = included[obj_id]
        if entry.type not in ("FR", "TR"):
            continue
        obj = entry.obj
        current_ids, history_ids = revision_window(obj, decs_by_id)
        for dec_id in current_ids:
            dec = decs_by_id.get(dec_id)
            if dec is None:
                notes.append(f"{obj_id}: revisions lists {dec_id}, which is not in the graph")
                continue
            consider(dec, f"revisions of {obj_id}")
        for dec_id in history_ids:
            dec = decs_by_id.get(dec_id)
            if dec is None:
                continue
            if dec_id not in included:
                excluded.append(
                    Excluded(dec_id, visibility(dec), f"revisions of {obj_id} (pre-breaking)")
                )
        listed = {str(r) for r in (getattr(obj, "revisions", None) or [])}
        for dec in sorted(decs, key=lambda d: str(d.id)):
            if str(getattr(dec, "revises", None)) == obj_id and str(dec.id) not in listed:
                # Open question default: include as current, with a note — but
                # only when it will actually be shown (class wins over window).
                if str(dec.id) not in included and visibility(dec) in DEFAULT_VIEW:
                    _, note = dec_window_class(dec, objs_by_id)
                    if note:
                        notes.append(note)
                consider(dec, f"revises {obj_id} (unlisted)")

    # 3. `constrained_by` FRs of every DEC in the set.
    for obj_id in sorted(included, key=_sort_key):
        entry = included[obj_id]
        if entry.type != "DEC":
            continue
        for fr_id in getattr(entry.obj, "constrained_by", None) or []:
            fr = frs_by_id.get(str(fr_id))
            if fr is not None:
                consider(fr, f"constrained_by of {obj_id}")

    # 4. ADRs of every DEC in the set.
    for obj_id in sorted(included, key=_sort_key):
        entry = included[obj_id]
        if entry.type != "DEC":
            continue
        for adr_id, edge in adr_refs_of(entry.obj):
            adr = adrs_by_id.get(adr_id)
            if adr is None:
                notes.append(f"{obj_id}: {edge} names {adr_id}, which has no ADR file")
                continue
            consider(adr, f"{edge} of {obj_id}")

    result.objects = [included[k] for k in sorted(included, key=_sort_key)]
    # De-duplicate exclusions (an object can be reached twice) deterministically.
    result.excluded = sorted(set(excluded), key=lambda e: (_sort_key(e.id), e.via))
    result.notes = sorted(set(notes))
    return result


# ---------------------------------------------------------------------------
# Provisional report (@implements FR-0005:AC-7)
# ---------------------------------------------------------------------------


@dataclass
class ProvisionalReport:
    as_of: date
    past: list[Any] = field(default_factory=list)
    pending: list[Any] = field(default_factory=list)
    event: list[Any] = field(default_factory=list)


def classify_trigger(trigger: str, as_of: date) -> str:
    """`past` when `trigger` parses as an ISO `YYYY-MM-DD` date `<= as_of`,
    `pending` when it parses and is later, `event` for any other string."""
    text = str(trigger).strip()
    if _ISO_DATE.match(text):
        try:
            when = date.fromisoformat(text)
        except ValueError:
            return "event"
        return "past" if when <= as_of else "pending"
    return "event"


def provisional(
    decs: Iterable[Any],
    as_of: date,
    objs_by_id: Mapping[str, Any] | None = None,
) -> ProvisionalReport:
    """Default-view DECs with a non-null `provisional_until`, grouped `past` /
    `pending` / `event` and sorted by ID within each group. `rejected`,
    `superseded` and — when `objs_by_id` is given — pre-breaking DECs are not
    reported. `as_of` is a parameter so tests and dashboards are deterministic.
    @implements FR-0005:AC-7"""
    report = ProvisionalReport(as_of=as_of)
    for dec in sorted(decs, key=lambda d: str(d.id)):
        trigger = getattr(dec, "provisional_until", None)
        if trigger is None:
            continue
        if not in_default_view(dec, objs_by_id):
            continue
        getattr(report, classify_trigger(trigger, as_of)).append(dec)
    return report


# ---------------------------------------------------------------------------
# Retired objects — INDEX.md's `Why` column (@implements FR-0005:AC-9)
# ---------------------------------------------------------------------------


def retired_reason(obj: Any, objs_by_id: Mapping[str, Any]) -> str | None:
    """Why an object is outside the default view, in INDEX.md's wording:
    `superseded by <ID>`, `superseded`, `rejected`, or
    `pre-breaking (<target> v<p+1> < v<last_breaking_revision>)`. None for an
    object in the default view."""
    cls = visibility(obj)
    if cls == "superseded":
        successor = getattr(obj, "superseded_by", None)
        return f"superseded by {successor}" if successor else "superseded"
    if cls == "rejected":
        return "rejected"
    if object_type(obj) == "DEC":
        return pre_breaking_reason(obj, objs_by_id)
    return None
