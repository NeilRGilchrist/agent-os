# stack-nested fixture trees (FR-0017)

Synthetic repo roots for `test_stack_nested_manifests.py`: node markers
(`package.json`, `pnpm-lock.yaml`, `yarn.lock`) one directory below the root
(DEC-0020 Decision 1), and the non-node markers that must stay root-only
(DEC-0020 Decision 2). Kept apart from `stack-profile/trees/`, whose
directory listing `test_stack_profile.py` pins exactly.

Trees that git cannot carry faithfully -- symlinks, dot-directories,
`node_modules/`, a directory named `package.json` -- are built per test in a
temporary directory instead of living here. Every file is synthetic.
