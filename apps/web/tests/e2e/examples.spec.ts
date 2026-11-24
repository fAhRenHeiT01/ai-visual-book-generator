import { expect, test, type Locator } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { components } from '../../src/types/generated';

type S = components['schemas'];
const corpus = JSON.parse(readFileSync(resolve('../api/src/bookgen/examples/manifest.json'), 'utf8')) as {
  scenarios: { id: string; title: string; expected: { export_blocked: boolean }; book_context: S['BookContext'] }[];
  visual_review_fixtures: Record<string, string>;
};
const api = 'http://127.0.0.1:8007/api/v1';
const localPython = resolve('../..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.PYTHON ?? (existsSync(localPython) ? localPython : 'python');

async function settled(canvas: Locator) {
  await expect(canvas).toHaveAttribute('data-settled', 'true');
  await expect(canvas).toHaveAttribute('data-overflow', 'false');
  return canvas.evaluate(element => {
    const content = element.querySelector('.page-content')!;
    const box = content.getBoundingClientRect();
    const rects = Array.from(content.children).map(child => child.getBoundingClientRect());
    return {
      overflow: rects.filter(rect => rect.top < box.top - 1 || rect.left < box.left - 1 || rect.bottom > box.bottom + 1 || rect.right > box.right + 1).length,
      headings: Array.from(content.querySelectorAll('h2')).map(heading => {
        const style = getComputedStyle(heading);
        return [style.fontSize, style.lineHeight, style.color];
      }),
      protectedMedia: Array.from(content.querySelectorAll('[data-protected-media="true"]')).map(frame => ({
        fit: getComputedStyle(frame.querySelector('img')!).objectFit,
        overlays: frame.querySelectorAll('[data-scrim]').length,
      })),
    };
  });
}

test('Examples opens the same scenario twice with independent review and edits', async ({ page, request }) => {
  await page.goto('/');
  await page.getByText('Examples · Explore 25 sample pages', { exact: true }).click();
  const open = page.getByRole('button', { name: 'A partnership built on clarity', exact: true });
  await open.click();
  await expect(page.getByRole('region', { name: 'Review page options' })).toBeVisible();
  const first = page.url().split('/').at(-1)!;
  await expect(page.getByText(/Scripted fixture run · portrait-testimonial/)).toBeVisible();
  await expect(page.locator('.examples')).toHaveCount(0);
  await page.getByRole('link', { name: 'Visual Book Generator', exact: true }).click();
  await page.getByText('Examples · Explore 25 sample pages', { exact: true }).click();
  await open.click();
  await expect(page).toHaveURL(/\/sessions\//);
  await expect.poll(() => page.url().split('/').at(-1)).not.toBe(first);
  const second = page.url().split('/').at(-1)!;
  await page.getByRole('button', { name: 'Confirm selection', exact: true }).click();
  const text = page.getByLabel('Page text');
  await expect(text).toBeVisible();
  await text.fill('Verbatim independent edit.');
  await page.getByRole('button', { name: 'Generate options', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Review page options' })).toBeVisible();
  const original = await (await request.get(`${api}/sessions/${first}`)).json() as S['SessionSnapshot'];
  expect(original.committed_pages).toEqual([]);
  expect(original.pending_review!.page_number).toBe(1);
  const edited = await (await request.get(`${api}/sessions/${second}`)).json() as S['SessionSnapshot'];
  expect(edited.committed_pages).toHaveLength(1);
  expect(edited.pending_review!.input_blocks[0].text).toBe('Verbatim independent edit.');
});

// Every case uses local manifest assets and the normal graph, review, publication
// decisions and export route. Saved baselines remain the reviewed Ticket 20 files.
for (const fixture of corpus.scenarios) {
  test(`scripted fixture ${fixture.id}: overflow, protected media, compliance and PDF parity`, async ({ page, request }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: 2200, height: 1400 });
    const external: string[] = [];
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { external.push(url.href); return route.abort(); }
      return route.continue();
    });
    const opened = await request.post(`${api}/examples/${fixture.id}/sessions`);
    expect(opened.status()).toBe(201);
    const session = await opened.json() as S['SessionSnapshot'];
    const sid = session.session_id;
    const result = session.pending_review!;
    const direction = session.context.resolved_direction!;
    const label = `${fixture.id}-${direction}-${session.context.page_size}`;
    await page.goto(`/sessions/${sid}`);
    await page.addStyleTag({ content: '.studio { max-width: none; }' });
    const baselines: string[][] = [];
    let before: Awaited<ReturnType<typeof settled>> | undefined;
    for (const [index, option] of ['option_a', 'option_b'].entries()) {
      const preview = page.locator('.option-card .page-canvas').nth(index);
      const facts = await settled(preview);
      expect(facts.overflow).toBe(0);
      expect(facts.protectedMedia.every(media => media.fit === 'contain' && media.overlays === 0)).toBe(true);
      if (index === 0) before = facts;
      const screenshot = await preview.screenshot({ animations: 'disabled', path: test.info().outputPath(`${label}-${option}-preview.png`) });
      if (Object.values(corpus.visual_review_fixtures).includes(fixture.id)) {
        const baseline = resolve('tests/e2e/page_design.spec.ts-snapshots', `${fixture.id}-${session.context.page_size}-option-${index ? 'b' : 'a'}.png`);
        const reviewed = readFileSync(baseline);
        writeFileSync(test.info().outputPath(`${label}-${option}-reviewed-baseline.png`), reviewed);
        baselines.push([screenshot.toString('base64'), reviewed.toString('base64')]);
      }
    }
    await page.getByRole('button', { name: 'Confirm selection', exact: true }).click();
    await expect(page.getByLabel('Page text')).toBeVisible();
    const prefix = `${api}/sessions/${sid}`;
    if (fixture.expected.export_blocked) {
      await expect(page.getByRole('button', { name: 'Download PDF', exact: true })).toBeDisabled();
      expect((await request.post(prefix + '/export', { data: {} })).status()).toBe(409);
      const report = await (await request.get(prefix + '/compliance')).json() as S['ComplianceReport'];
      for (const entry of report.ledger ?? []) {
        const decision = await request.post(prefix + '/compliance/decisions', { data: { page_id: result.page_id, metric_id: entry.metric.metric_id, action: 'approve' } });
        expect(decision.status()).toBe(200);
      }
    }
    await page.goto(`/print/${sid}`);
    await expect(page.locator('html')).toHaveAttribute('data-print-ready', 'true');
    const printed = page.locator('.print-page[data-kind="body"] .page-canvas');
    const facts = await settled(printed);
    expect(facts).toEqual(before);
    await page.emulateMedia({ media: 'print' });
    const png = await printed.screenshot({ animations: 'disabled', path: test.info().outputPath(`${label}-print.png`) });
    const exported = await request.post(prefix + '/export', { data: {}, timeout: 120_000 });
    expect(exported.status(), await exported.text()).toBe(200);
    const pdf = await exported.body();
    writeFileSync(test.info().outputPath(`${label}-scripted.pdf`), pdf);
    const verified = spawnSync(python, ['-X', 'utf8', resolve('../api/tests/golden/verify_artifacts.py')], {
      input: JSON.stringify({ case_id: fixture.id, direction, pdf: pdf.toString('base64'), png: png.toString('base64'), page_count: 3,
        text: result.input_blocks.map(block => block.text), baselines }), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve('../api/src') },
    });
    expect(verified.status, verified.stderr).toBe(0);
    expect(external).toEqual([]);
    const metrics = JSON.stringify({ ...JSON.parse(verified.stdout), preview_overflow: facts.overflow,
      protected_media_count: facts.protectedMedia.length, source_blocks: result.input_blocks.length,
      asset_count: result.input_assets.length, repair_attempts: result.repair_attempts,
      used_fallback: result.used_fallback, compliance_gate_observed: fixture.expected.export_blocked,
      preview_print_parity: true, external_fetches: external.length }, null, 2);
    writeFileSync(test.info().outputPath(`${label}-metrics.json`), metrics);
    await test.info().attach(`${label}-scripted-fixture-metrics`, { body: metrics, contentType: 'application/json' });
  });
}
