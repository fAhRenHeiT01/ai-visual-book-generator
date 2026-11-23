import { expect, test } from '@playwright/test';
import type { components } from '../../src/types/generated';

test('manual debug steps survive refresh and render semantic theme roles before explicit commit', async ({ page, request }) => {
  test.skip(process.env.BOOKGEN__APP__DEBUG_MODE !== 'true', 'Run with BOOKGEN__APP__DEBUG_MODE=true');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Create book' }).click();
  await page.getByLabel('Page text').fill('Exact manual body.');
  await page.getByLabel('Page images').setInputFiles({ name: 'chart.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFUlEQVR4nGP8//8/AyHARFDFsFcEAHkjAw3jrppVAAAAAElFTkSuQmCC', 'base64') });
  await page.getByRole('button', { name: 'Generate options' }).click();
  for (const node of ['profile', 'compliance_metrics_scan', 'generate_candidates']) {
    await page.getByRole('button', { name: `Run ${node}`, exact: true }).click();
  }
  await expect(page.getByLabel('Chat prompt')).toHaveValue(/You are the book's art director/);
  await expect(page.getByLabel('Chat prompt')).toHaveValue(/Exact manual body\./);
  await expect(page.getByRole('button', { name: 'Copy prompt' })).toBeVisible();
  const originalPrompt = await page.getByLabel('Chat prompt').inputValue();
  await page.reload();
  await expect(page.getByLabel('Chat prompt')).toHaveValue(originalPrompt);
  const thumbnail = page.getByRole('link', { name: /Download .* thumbnail/ });
  await expect(thumbnail).toHaveAttribute('href', /^data:image\/png;base64,/);
  const assetId = (await thumbnail.getAttribute('download'))!.slice(0, -4);
  await expect(page.getByRole('img', { name: `${assetId} thumbnail for chat` })).toBeVisible();
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
  await expect(page.locator('.option-card').first().getByText('Exact manual body.', { exact: true })).toBeVisible();
  const canvas = page.locator('.option-card').first().getByTestId('page-canvas');
  await expect(canvas).toHaveCSS('background-color', 'rgb(243, 244, 246)');
  await page.getByText('Theme tokens and semantic placeholders', { exact: true }).click();
  await expect(page.getByText('--color-brand-primary', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm selection' }).click();
  const sid = page.url().split('/').at(-1)!;
  const before = await request.get(`http://127.0.0.1:8007/api/v1/sessions/${sid}`);
  expect((await before.json()).committed_pages).toHaveLength(0);
  await page.getByRole('button', { name: 'Run commit_page', exact: true }).click();
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
