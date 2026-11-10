# dispatch-subdirectory fixtures

Synthetic inputs for `tests/unit/scripts/test_dispatch_subdirectory.py`
(hub-tooling FR-0024, a dispatcher for a project in a subdirectory of its
repository). The tests build a real git repository whose project lives in
`projects/demo/` and copy these files into it:

| File | Where the test puts it | Why |
|---|---|---|
| `decoy-REVIEW.md` | `REVIEW.md` at the repository top | must never be read, filed or reported as the project's review |
| `decoy-library-review.md` | `specs/_reviews/FR-0001-r1.md` at the repository top | must never be read as the project's filed review |
| `decoy-PR_BODY.md` | `PR_BODY.md` at the repository top | must never become the project's PR body |
| `project-PR_BODY.md` | `projects/demo/PR_BODY.md` | the body the project's PR must carry |
| `reviewer-REVIEW.md` | `projects/demo/REVIEW.md` on the Reviewer branch | the Reviewer's own handoff, filed into the library |
| `legacy-REVIEW.md` | `projects/demo/REVIEW.md` on `main` | a legacy root review the filing commit restores (DEC-0028) |
| `layout-repo.yaml` | `projects/demo/.agent-team/layout.yaml` | `footprint_root: repo` |
| `layout-malformed.yaml` | `projects/demo/.agent-team/layout.yaml` | a value FR-0023's loader refuses |

Every file is synthetic: no real people, records or identifiers.
