# Native source oracles

These fixtures replace test-time `git show HEAD` or historical-object reads.
They work in a sealed source archive and shallow CI checkout. The tests do not
invoke Git, create an account, or access a database. `baseline.json` itself is
SHA-256 pinned in `tests/native_source_oracle.py`.

Baseline objects were read once from this repository with `git show
<full-commit>:<module>` and `git rev-parse <full-commit>:<module>`. The JSON records
the complete commit, blob ID and source SHA-256 for independent provenance review.
Fingerprints include all semantic AST fields, omitting only positions and empty
Python 3.12+ `type_params`; nonempty generic parameters remain significant.

* Master settings: `fc039feff813b6d27949bca98f81626774a6076c`, the parent of
  presentation commit `ff942c4`. Compare every native function after removing
  exactly the two separately fingerprinted `lihat` presentation nodes.
* Alat: `59a15198fda21a6e0afc0a7732aa2e856d2b4eed`, the parent of `2e17865`.
  Compare every native function, including every writer. Only the declared
  Alat block and the later `7cddbb5` six-settings block are removed after their
  exact fingerprints are checked. The separate six-settings tests keep their
  own baseline and permission checks.
* Stock detail: original `88560d962f61f027c9b2c77cbda3d19f53104384` native
  pre-render statements and render arguments, unchanged in scope from the former
  Git-based assertions.
* Karung: original `e7f6370af0c0620d040cd16de10897a43dc3e5fc` complete source
  bytes for the held ownership editor/controller, plus the original native
  pre-render statements and arguments for the three stock routes.
* QC list: original `d147691f1650d623df2a2f5ebda5b0665e43404f` complete row-loop
  branch and static header bytes, unchanged in scope from the former assertion.

Nonexecuted negative controls alter a real writer commit, native dependency
guard, guarded pre-render prefix, held source bytes, QC row expression or header.
Each must differ from its fixed oracle. No expected value is generated from the
current checkout during a test; intentional native changes need an explicit
baseline/provenance review rather than silently following HEAD.
