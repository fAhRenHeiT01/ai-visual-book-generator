# TICKET-13 — Marketing fixture corpus

**Status:** Open · **Predecessor:** [Ticket 12](TICKET-12.md)

Build a reusable offline corpus of 25 marketing pages.

## Implementation

- Give each case an ID, book context, verbatim copy, local asset references, expected design and compliance behavior, and coverage tags. Record the origin and reuse rights of every image. Use actual decodable files for photos, charts, diagrams, and logos.
- Include 500-word executive prose without imagery, a one-sentence opener with a wide photo, paired financial charts and insights, a headshot with a diagram and testimonial, and client-facing restricted metrics. Include low-resolution, boundary-sized, extreme-aspect, and mixed-format assets.
- Map the corpus to every supported archetype, component type, asset kind, both audiences and paper sizes, plus ordinary, repair, fallback, and export-blocked cases. Ticket 23 consumes this corpus for the gallery and CI.

## TDD and acceptance

**First failing test.** Write a corpus integrity test that loads the manifest and enumerates missing scenarios or assets.

- Exactly 25 unique scenario IDs resolve to usable copy and assets offline. Validate paths, dimensions, kinds, provenance, and the coverage matrix.
- Identify the opener, two-chart comparison, and portrait testimonial as stable visual review fixtures for Tickets 19–23.
- Run the [shared exit gates](BACKLOG_DAG.md#shared-exit-gates) before closing the ticket.

## File ownership

- `apps/api/src/bookgen/examples/`
- `apps/api/tests/golden/test_corpus.py`
