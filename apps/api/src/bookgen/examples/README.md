# Offline marketing corpus

`manifest.json` contains exactly 25 fictional marketing page scenarios and a
catalogue of 14 local, decodable images. No provider or network call is needed to
load, profile, validate or render the corpus. All paths resolve relative to this
directory. Keep scenario IDs stable: later art-direction, gallery and CI tickets
consume them.

The visual review anchors are:

| Review role | Scenario ID |
| --- | --- |
| One-sentence opener with wide photograph | `chapter-opener` |
| Paired financial charts and bullet insights | `financial-comparison` |
| Portrait, diagram and exact testimonial excerpt | `portrait-testimonial` |

Each scenario supplies canonical `BookContext` data, verbatim `copy`, ordered
asset-catalogue keys, coverage tags, expected design/compliance behavior, and two
valid `PageLayoutAST` reference options. These are deterministic reference
layouts, not claims about a live model's output. Profile the copy and assets in
manifest order to obtain their stable `blk_01` / `img_01` pointers. Resolve an
asset's `path` locally, pass its bytes, explicit `kind` and `alt_caption` into
`ImageInput`, and retain the profiler's original/thumbnail storage mapping.
Never substitute the catalogue key for the profiler's page-local asset ID.

`coverage_matrix` maps every supported archetype, component type, asset kind,
audience, paper size and expected outcome to concrete scenario IDs. It is checked
against the actual reference layouts, inputs and canonical Python enums. The
cases include exactly 500 words without imagery, restricted client metrics,
transparent and mixed-format assets, low DPI, extreme proportions, and sources
with longest edges of 767, 768 and 769 pixels. Original large images stay local;
provider thumbnails remain bounded by the YAML profiling settings.

`expected.outcome` describes the intended later regression flow:

- `normal`: return the reference pair on the first scripted provider call.
- `repair`: apply the named `failure_probe.mutation` to the first option, assert
  its `issue_code`, then return the reference pair during repair.
- `fallback`: repeat the named invalid mutation through the configured repair
  budget, then assert complete safe fallback. The supplied reference pair shows
  valid final source placement; exact fallback rationale and components may
  follow the configured builder.
- `export-blocked`: commit a valid reference layout and verify that export is
  blocked until the restricted metrics receive an explicit publication decision.

Failure probes are declarative fixture data. The integrity suite checks their
actual validator errors; Ticket 23 owns end-to-end graph/gallery execution. Use
`MockLLMProvider` with the scripts above for graph tests. Do not call live models.
`expected.export_blocked` assumes a committed selection with no compliance
approvals; an uncommitted or pending-review page has its own export gate.

Run the corpus gate from the repository root:

```text
python -m pytest -W error apps/api/tests/golden/test_corpus.py
```

The existing `make backend` target does not discover `tests/golden`, so run this
command explicitly until Ticket 23 integrates the golden suite into CI.

## Copy and image provenance

All marketing copy, chart data, diagrams and the fictional Northstar Studio logo
are original fixtures dedicated under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
Charts contain visible labels, values, axes and synthetic-data source notes;
diagrams contain real stage labels and connectors. They are not blank placeholder
files. No performance claim describes a real company.

Photographs are derivatives of NASA public-domain works, with source pages,
download origins, modifications, rights and SHA-256 hashes recorded individually
in the manifest:

- [Earthrise, NASA / William Anders](https://commons.wikimedia.org/wiki/File:NASA-Apollo8-Dec24-Earthrise.jpg).
- [Buzz Aldrin, NASA S69-31743](https://commons.wikimedia.org/wiki/File:Buzz_Aldrin.jpg),
  obtained from the NASA image archive directly.

The historical portrait is a layout specimen. The fictional testimonial is not
attributed to Buzz Aldrin and does not imply his or NASA's endorsement. The page
copy and asset caption retain that distinction. Public-domain copyright status
does not grant personality or endorsement rights. No NASA mark is used as the
fictional brand logo.

Tests verify local paths, hashes, successful decoding, dimensions, MIME and asset
kinds, provenance completeness, real image variation, preflight warnings,
bounded derivatives, valid complete pointer layouts, exact excerpts, protected
media behavior and compliance classifications. Updating an image requires an
intentional metadata/hash update and review of its provenance and dimensions.
