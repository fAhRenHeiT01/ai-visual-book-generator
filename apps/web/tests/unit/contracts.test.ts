import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import type { components } from "../../src/types/generated";

const fixture = {
  option_id: "option_a",
  strategy_tag: "editorial_visual",
  archetype: "editorial_asymmetric",
  rationale: "Pair the source prose with its chart.",
  surface_role: "paper",
  density_scale: "normal",
  components: [{
    component_id: "cmp_01",
    component_type: "body_prose",
    slot_id: "col_left",
    source_block_ids: ["blk_01"],
    source_asset_id: null,
    extracted_excerpt: null,
    object_fit: "contain",
    surface_role: "paper",
    emphasis: false,
  }],
  column_count: 1,
} satisfies components["schemas"]["PageLayoutAST"];

// @ts-expect-error The published grammar rejects unrecognized archetypes.
const invalidArchetype: components["schemas"]["LayoutArchetype"] = "invented_layout";
void invalidArchetype;

test("the committed OpenAPI grammar includes the typed fixture archetype", () => {
  const artifact = resolve("../api/openapi.json");
  expect(existsSync(artifact), "OpenAPI contract must be committed").toBe(true);
  const openapi = JSON.parse(readFileSync(artifact, "utf8"));
  expect(openapi.components.schemas.LayoutArchetype.enum).toContain(fixture.archetype);
  expect(openapi.components.schemas.LayoutArchetype.enum).toHaveLength(11);
});
