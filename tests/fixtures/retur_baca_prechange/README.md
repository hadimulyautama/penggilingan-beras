# Staff return read baseline

Source-only provenance: full commit `05d3651accc0f012909bc21da6b9e131c62b1ca4`.
`baseline.json` records Git blob/source SHA and portable semantic AST fingerprints.
Its SHA-256 is pinned in the test. Historical Git objects are not read at runtime.

The three adopted GET functions only assign their existing complete native
render to `response`, import the presentation decorator, and return that
response through it. The test reconstructs the original return and compares
all native function ASTs, including every unchanged reader and POST writer.
A nonexecuted commit→rollback control must differ from the writer oracle.

For `retur_daftar.html`, the test reverses exactly the two section provenance
attributes and two native empty-state table wrappers. The reconstructed source
must match the original SHA; no nonempty row expression, total, paging or message
may change. The detail/application/ticket templates, original controllers and
supplier route sources remain byte-identical. These tests are not a browser,
permission integration, physical return, partial-return or stock mutation proof.
