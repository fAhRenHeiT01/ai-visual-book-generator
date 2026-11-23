# Visual Book Generator delivery backlog

**Tickets 01–10 are complete. Tickets 11–23 remain open. Start with [Ticket 11](TICKET-11.md) and work through Ticket 23 in numerical order.** Each open ticket is one PR. Merge it after its acceptance criteria pass, then start its successor.

## Remaining work

The predecessor column defines the delivery order. Tickets 13 and 23 split fixture authoring from the showcase and regression suite. Tickets 18 and 22 split library persistence from its editor. Tickets 19, 20, and 21 own design decisions in the layout model, their HTML/CSS rendering, and the surrounding authoring UI respectively.

| Ticket | Predecessor | Outcome |
| --- | --- | --- |
| [11 · Manual node-by-node debugger](TICKET-11.md) | 10 (complete) | Verify and finish the existing checkpoint debugger, manual prompts, and review flow. |
| [12 · Recover failed page generation](TICKET-12.md) | 11 | Generate a page safely after an interrupted request. |
| [13 · Marketing fixture corpus](TICKET-13.md) | 12 | Build a reusable offline corpus of 25 marketing pages. |
| [14 · Metadata-only provider requests](TICKET-14.md) | 13 | Send asset metadata to layout providers. |
| [15 · Resolution-based render derivatives](TICKET-15.md) | 14 | Use smaller images only when rendering needs a derivative. |
| [16 · Dedicated debug workspace](TICKET-16.md) | 15 | Move manual debugging to a dedicated session workspace. |
| [17 · Source span grouping](TICKET-17.md) | 16 | Let the model group exact source spans once per page. |
| [18 · Reusable theme library](TICKET-18.md) | 17 | Save reusable extracted themes across books. |
| [19 · Context-aware art direction](TICKET-19.md) | 18 | Choose a book direction and generate meaningful page treatments. |
| [20 · Print page art direction](TICKET-20.md) | 19 | Render deck-quality treatments on the shared print canvas. |
| [21 · Enterprise authoring workspace](TICKET-21.md) | 20 | Polish the enterprise authoring workspace. |
| [22 · Theme library and palette UI](TICKET-22.md) | 21 | Make the theme library and palette editor usable in Studio. |
| [23 · Interactive examples and golden gates](TICKET-23.md) | 22 | Open example books and run golden regressions in CI. |

## Shared exit gates

- Read the [project instructions](../AGENTS.md) and the [architecture and TDD spec](../ai_powered_visual_book_generator_technical_architecture_tdd_execution_plan.md). Each ticket lists the paths it owns. A trailing slash grants ownership of that subtree.
- Write the focused test first, observe its expected failure, implement, and record the passing result. Inject `MockLLMProvider` in unit and graph tests.
- Run `make backend`, `make frontend`, `make typecheck`, and `make check-contracts`. Regenerate schema changes with `make sync-contracts`. Run the affected browser and PDF flows and the existing coverage gates. Include the full browser flow and golden suite at Ticket 23.
- Preserve source pointers, exact excerpts, protected chart/diagram rendering, and bounded provider context. Load design rules, thresholds, prompts, and retry budgets from YAML. Verify old persisted data wherever a contract changes.

## Completed work

| Completed ticket | Delivered after |
| --- | --- |
| [01 · Config and test harness](TICKET-01.md) | — |
| [02 · Python/OpenAPI/TS contracts](TICKET-02.md) | 01 |
| [03 · Profiling and local assets](TICKET-03.md) | 02 |
| [04 · Validation and fallback](TICKET-04.md) | 02 |
| [05 · Generation and session API](TICKET-05.md) | 03, 04 |
| [06 · Page rendering and overflow](TICKET-06.md) | 02, 04 |
| [07 · Browser studio and draft](TICKET-07.md) | 05, 06 |
| [08 · Metrics and sign-off](TICKET-08.md) | 07 |
| [09 · Brand and chrome](TICKET-09.md) | 07, 08 |
| [10 · Assembly and PDF](TICKET-10.md) | 08, 09 |
