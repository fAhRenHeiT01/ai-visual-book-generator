import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { components } from '../../src/types/generated';

test.use({ timezoneId: 'America/Los_Angeles' });

test('approved draft downloads assembled PDF with redacted metrics and numbered chrome', async ({ page, request }) => {
  test.setTimeout(120_000);
  await page.clock.setFixedTime(new Date('2026-01-02T03:04:00Z'));
  const api = 'http://127.0.0.1:8007/api/v1/sessions';
  const created = await request.post(api, { data: { context: { title: 'Public report', audience_mode: 'client_facing' } } });
  const sid = (await created.json()).session_id;
  const python = process.env.PYTHON ?? resolve('../..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const fixture = spawnSync(python, ['-c', 'import base64,io,json; from PIL import Image; images=[]\nfor size in [(1200,800),(320,480)]:\n b=io.BytesIO(); Image.new("RGB",size,"white").save(b,"JPEG"); images.append(base64.b64encode(b.getvalue()).decode())\nprint(json.dumps(images))'], { encoding: 'utf8' });
  expect(fixture.status).toBe(0);
  const assets: components['schemas']['ImageAssetMeta'][] = [];
  for (const [index, encoded] of (JSON.parse(fixture.stdout) as string[]).entries()) {
    const upload = await request.post(`${api}/${sid}/assets`, { multipart: { files: { name: index ? 'diagram.jpg' : 'chart.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(encoded, 'base64') } } });
    expect(upload.status()).toBe(201);
    assets.push((await upload.json()).assets[0]);
  }
  expect(assets[0].thumbnail_key).toBeTruthy();
  expect(assets[1].thumbnail_key).toBeNull();
  const generated = await request.post(`${api}/${sid}/pages`, { data: { text: '[INTERNAL] $4.2M ARR\n\nPublishable conclusion.', asset_ids: assets.map(asset => asset.asset_id) } });
  const result = await generated.json();
  await page.goto(`/sessions/${sid}`);
  for (const [index, asset] of assets.entries()) {
    const image = page.locator(`.option-card img[src$="/assets/${asset.asset_id}"]`).first();
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate(img => (img as HTMLImageElement).currentSrc)).toBe(`${api}/${sid}/assets/${asset.asset_id}${index ? '' : '?thumbnail=true'}`);
    await expect(image).toHaveClass(/object-contain/);
    await expect(image.locator('xpath=ancestor::figure').locator('[data-scrim]')).toHaveCount(0);
  }
  await request.post(`${api}/${sid}/pages/${result.page_id}/selection`, { data: { option_id: 'option_a' } });
  const report = await (await request.get(`${api}/${sid}/compliance`)).json();
  await request.post(`${api}/${sid}/compliance/decisions`, { data: { page_id: result.page_id, metric_id: report.ledger[0].metric.metric_id, action: 'redact' } });
  await page.goto(`/sessions/${sid}`);
  const large = page.locator(`.draft-viewer img[src$="/assets/${assets[0].asset_id}"]`);
  const small = page.locator(`.draft-viewer img[src$="/assets/${assets[1].asset_id}"]`);
  await expect.poll(() => large.evaluate(img => (img as HTMLImageElement).currentSrc)).toBe(`${api}/${sid}/assets/${assets[0].asset_id}?thumbnail=true`);
  await expect.poll(() => large.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(768);
  await expect.poll(() => small.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(320);
  await page.emulateMedia({ media: 'print' });
  await expect.poll(() => large.evaluate(img => (img as HTMLImageElement).currentSrc)).toBe(`${api}/${sid}/assets/${assets[0].asset_id}`);
  await expect.poll(() => large.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBe(1200);
  await page.emulateMedia({ media: 'screen' });
  const action = page.getByRole('button', { name: 'Download PDF' });
  await expect(action).toBeEnabled();
  const downloaded = page.waitForEvent('download');
  await action.click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe('Public report_20260101-1904.pdf');
  const extracted = spawnSync(python, ['-c', 'import sys,io; from pypdf import PdfReader; r=PdfReader(io.BytesIO(sys.stdin.buffer.read())); print(len(r.pages)); print("\\n".join(p.extract_text() for p in r.pages)); print(sorted({image.image.size for page in r.pages for image in page.images}))'], { input: readFileSync((await download.path())!), encoding: 'utf8' });
  expect(extracted.status).toBe(0);
  expect(extracted.stdout.split('\n')[0].trim()).toBe('3');
  expect(extracted.stdout).toContain('Contents');
  expect(extracted.stdout).toContain('Page 3 of 3');
  expect(extracted.stdout).toContain('Publishable conclusion.');
  expect(extracted.stdout).toContain('[REDACTED]');
  expect(extracted.stdout).not.toContain('$4.2M ARR');
  expect(extracted.stdout).toContain('(1200, 800)');
  expect(extracted.stdout).toContain('(320, 480)');
  await page.goto(`/print/${sid}`);
  await expect.poll(() => page.locator('html').getAttribute('data-print-ready')).toBe('true');
  await expect(page.locator('.print-book source')).toHaveCount(0);
  for (const asset of assets) {
    const image = page.locator(`.print-book img[src$="/assets/${asset.asset_id}"]`);
    await expect.poll(() => image.evaluate(img => (img as HTMLImageElement).currentSrc)).toBe(`${api}/${sid}/assets/${asset.asset_id}`);
    await expect(image).toHaveClass(/object-contain/);
    await expect(image.locator('xpath=ancestor::figure').locator('[data-scrim]')).toHaveCount(0);
  }
});


test('session theme stays light across preview, semantic pages, assembled covers and contents', async ({ page, request }) => {
  const api = 'http://127.0.0.1:8007/api/v1/sessions';
  const created = await request.post(api, { data: { context: { title: 'Ocean field notes' } } });
  const sid = (await created.json()).session_id;
  const applied = await request.post(`${api}/${sid}/appearance/theme`, { data: { theme_id: 'ocean' } });
  expect(applied.status()).toBe(200);
  const appearance = await applied.json();
  await page.goto(`/sessions/${sid}`);
  await page.getByText('Book appearance', { exact: true }).click();
  await expect(page.getByText(/Appearance locks when you start creating page 1/)).toBeVisible();
  const preview = page.locator('.theme-miniature .page-canvas');
  await expect(preview).toHaveAttribute('data-settled', 'true');
  for (const type of ['heading', 'body_prose', 'bullet_list', 'divider_rule', 'pull_quote', 'stat_callout']) {
    await expect(preview.locator(`.block-${type}`)).toBeVisible();
  }
  const previewTitle = await preview.locator('.block-heading').evaluate(element => getComputedStyle(element).color);
  const generated = await request.post(`${api}/${sid}/pages`, { data: { text: 'Field results\n\nA clear story with an exact source quote.' } });
  expect(generated.status()).toBe(201);
  const result = await generated.json();
  expect((await request.post(`${api}/${sid}/pages/${result.page_id}/selection`, { data: { option_id: result.option_a.option_id } })).status()).toBe(200);
  await page.goto(`/print/${sid}`);
  await expect.poll(() => page.locator('html').getAttribute('data-print-ready')).toBe('true');
  const cover = page.locator('[data-kind="cover"] .page-canvas');
  const toc = page.locator('[data-kind="toc"]');
  const body = page.locator('[data-kind="body"] .page-canvas');
  for (const canvas of [cover, toc.locator('.page-canvas'), body]) {
    await expect(canvas).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    expect(await canvas.evaluate(element => getComputedStyle(element).getPropertyValue('--color-brand-primary').trim())).toBe(appearance.tokens.color_brand_primary);
  }
  await expect(cover.locator('.block-heading')).toHaveCSS('color', previewTitle);
  const cssColor = (hex: string) => `rgb(${[1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16)).join(', ')})`;
  await expect(toc.locator('.print-toc')).toHaveCSS('color', cssColor(appearance.tokens.color_ink_primary));
  await expect(toc.locator('.print-toc a')).toHaveCSS('border-bottom-color', cssColor(appearance.tokens.color_brand_primary));
  for (const surface of [cover.locator('.block-heading'), toc.locator('.block-heading')]) {
    const brightness = await surface.evaluate(element => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 1;
      const context = canvas.getContext('2d')!;
      context.fillStyle = getComputedStyle(element).backgroundColor;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data].slice(0, 3).reduce((sum, value) => sum + value, 0);
    });
    expect(brightness).toBeGreaterThan(650);
  }
});
