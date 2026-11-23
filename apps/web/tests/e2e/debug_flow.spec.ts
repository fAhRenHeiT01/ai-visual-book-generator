import { expect, test } from '@playwright/test';
import type { components } from '../../src/types/generated';

test('normal Studio authoring stays available with the debugger capability enabled', async ({ page }) => {
  test.skip(process.env.BOOKGEN__APP__DEBUG_MODE !== 'true', 'Run with BOOKGEN__APP__DEBUG_MODE=true');
  await page.goto('/');
  await page.getByRole('button', { name: 'Create book' }).click();
  await expect(page.getByRole('link', { name: 'Open debugger' })).toBeVisible();
  await expect(page.getByLabel('Graph debugger')).toHaveCount(0);
  await page.getByLabel('Page text').fill('Ordinary authoring with debugging available.');
  await page.getByRole('button', { name: 'Generate options' }).click();
  await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm selection' }).click();
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
});

test('dedicated manual workspace copies prompts, repairs layouts and reopens before explicit commit', async ({ page, request, context }) => {
  test.skip(process.env.BOOKGEN__APP__DEBUG_MODE !== 'true', 'Run with BOOKGEN__APP__DEBUG_MODE=true');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Create book' }).click();
  await expect(page.getByRole('link', { name: 'Open debugger' })).toBeVisible();
  const sid = page.url().split('/').at(-1)!;
  await page.getByRole('link', { name: 'Open debugger' }).click();
  await expect(page).toHaveURL(`/sessions/${sid}/debug`);
  await page.getByLabel('Page text').fill('Exact manual body.');
  await page.getByLabel('Page images').setInputFiles({ name: 'chart.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFUlEQVR4nGP8//8/AyHARFDFsFcEAHkjAw3jrppVAAAAAElFTkSuQmCC', 'base64') });
  await page.getByRole('button', { name: 'Generate options' }).click();
  await expect(page.getByRole('button', { name: 'Run profile', exact: true })).toBeVisible();
  const paused = await (await request.get(`http://127.0.0.1:8007/api/v1/sessions/${sid}/debug`)).json();
  await request.post(`http://127.0.0.1:8007/api/v1/sessions/${sid}/debug/step`, { data: { checkpoint_id: paused.checkpoint_id } });
  await page.getByRole('button', { name: 'Run profile', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Stale checkpoint' })).toBeVisible();
  for (const node of ['compliance_metrics_scan', 'generate_candidates']) {
    await page.getByRole('button', { name: `Run ${node}`, exact: true }).click();
  }
  await expect(page.getByLabel('Chat prompt')).toHaveValue(/You are the book's art director/);
  await expect(page.getByLabel('Chat prompt')).toHaveValue(/Exact manual body\./);
  await expect(page.getByRole('button', { name: 'Copy prompt' })).toBeVisible();
  const originalPrompt = await page.getByLabel('Chat prompt').inputValue();
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.getByRole('button', { name: 'Copy prompt' }).click();
  await expect(page.getByText('Prompt copied.', { exact: true })).toBeVisible();
  // Windows clipboard text uses CRLF; the prompt field uses DOM LF newlines.
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied.replaceAll('\r\n', '\n')).toBe(originalPrompt);
  await page.reload();
  await expect(page.getByLabel('Chat prompt')).toHaveValue(originalPrompt);
  await expect(page.getByRole('link', { name: /Download .* thumbnail/ })).toHaveCount(0);
  expect(originalPrompt).not.toMatch(/inline_data|base64|storage_key|thumbnail_key|IMAGE ATTACHMENTS/);
  expect(originalPrompt).toContain('"asset_kind": "chart"');
  expect(originalPrompt).toContain('"width_px": 12');
  const assetId = originalPrompt.match(/"asset_id": "([^"]+)"/)![1];
  // Invalid replies use the same deterministic validator and repair node.
  for (const option of ['option_a', 'option_b']) {
    await page.getByLabel('Manual LLM response').fill(`invalid JSON ${option}`);
    await page.getByRole('button', { name: 'Submit response' }).click();
    if (option === 'option_a') await expect(page.getByLabel('Manual LLM response')).toHaveValue('');
  }
  await page.getByRole('button', { name: 'Run validate', exact: true }).click();
  const timeline = page.getByRole('list', { name: 'Node timeline' });
  await timeline.getByText('validate validation issues', { exact: true }).click();
  await expect(timeline.locator('[data-node="validate"]')).toContainText('SCHEMA_VALIDATION_ERROR');
  await page.getByRole('button', { name: 'Run repair', exact: true }).click();
  await expect(page.getByLabel('Chat prompt')).toHaveValue(/repair|Repair/);
  for (const option_id of ['option_a', 'option_b'] as const) {
    const layout: components['schemas']['PageLayoutAST'] = {
      option_id, strategy_tag: option_id === 'option_a' ? 'editorial_visual' : 'executive_structured',
      archetype: option_id === 'option_a' ? 'minimalist_swiss' : 'two_col_executive',
      rationale: 'Manual semantic role verification', surface_role: 'surface_tint', density_scale: 'normal',
      column_count: option_id === 'option_a' ? 1 : 2,
      components: [{ component_id: 'body', component_type: 'body_prose', slot_id: 'body',
        source_block_ids: ['blk_01'], source_asset_id: null, extracted_excerpt: null,
        object_fit: 'contain', surface_role: 'paper', emphasis: false },
      { component_id: 'image', component_type: 'image_frame', slot_id: 'media_main',
        source_block_ids: [], source_asset_id: assetId, extracted_excerpt: null,
        object_fit: 'contain', surface_role: 'paper', emphasis: false }],
    };
    await page.getByLabel('Manual LLM response').fill(JSON.stringify(layout));
    await page.getByRole('button', { name: 'Submit response' }).click();
    if (option_id === 'option_a') await expect(page.getByLabel('Manual LLM response')).toHaveValue('');
  }
  for (const node of ['validate', 'build_review', 'human_review_interrupt']) {
    await page.getByRole('button', { name: `Run ${node}`, exact: true }).click();
  }
  await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
  const studio = await context.newPage();
  await studio.goto(`/sessions/${sid}`);
  await expect(studio.getByRole('link', { name: 'Open debugger' })).toBeVisible();
  await expect(studio.getByRole('radio')).toHaveCount(0);
  await expect(studio.getByLabel('Page text')).toHaveCount(0);
  await studio.close();
  await expect(page.locator('.option-card').first().getByText('Exact manual body.', { exact: true })).toBeVisible();
  const canvas = page.locator('.option-card').first().getByTestId('page-canvas');
  await expect(canvas).toHaveCSS('background-color', 'rgb(243, 244, 246)');
  await page.getByText('Theme tokens and semantic placeholders', { exact: true }).click();
  await expect(page.getByText('--color-brand-primary', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm selection' }).click();
  const before = await request.get(`http://127.0.0.1:8007/api/v1/sessions/${sid}`);
  expect((await before.json()).committed_pages).toHaveLength(0);
  await page.getByRole('button', { name: 'Run commit_page', exact: true }).click();
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
