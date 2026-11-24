import { expect, test, type Locator } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import type { components } from '../../src/types/generated';

type S = components['schemas'];
const examples = resolve('../api/src/bookgen/examples');
const corpus = JSON.parse(readFileSync(resolve(examples, 'manifest.json'), 'utf8')) as {
  assets: Record<string, { path: string; mime_type: string }>;
  scenarios: { id: string; copy: string; assets: string[]; book_context: S['BookContext'] }[];
};
const reviews = [
  { id: 'chapter-opener', direction: 'campaign_presentation', composition: 'opener' },
  { id: 'financial-comparison', direction: 'consulting_report', composition: 'comparison' },
  { id: 'portrait-testimonial', direction: 'brand_led_editorial', composition: 'portrait_story' },
] as const;
const api = 'http://127.0.0.1:8007/api/v1/sessions';
const localPython = resolve('../..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = process.env.PYTHON ?? (existsSync(localPython) ? localPython : 'python');

async function geometry(canvas: Locator) {
  await expect(canvas).toHaveAttribute('data-settled', 'true');
  await expect(canvas).toHaveAttribute('data-overflow', 'false');
  await expect(canvas).toHaveAttribute('data-safe-flow', 'false');
  return canvas.evaluate(element => {
    const content = element.querySelector('.page-content')!;
    const box = content.getBoundingClientRect();
    const heading = element.querySelector('h2')!;
    const style = getComputedStyle(heading);
    const children = Array.from(content.children);
    const rects = children.map(child => child.getBoundingClientRect());
    const collisions = rects.flatMap((a, i) => rects.slice(i + 1).filter(b =>
      Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
      Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1));
    return {
      width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height,
      heading: { size: style.fontSize, leading: style.lineHeight, weight: style.fontWeight, color: style.color, margin: style.marginBlockStart },
      quoteSize: element.querySelector('blockquote') ? getComputedStyle(element.querySelector('blockquote')!).fontSize : null,
      paints: children.filter(child => child.textContent).map(child => {
        const paint = getComputedStyle(child);
        return { foreground: paint.color, background: paint.backgroundColor };
      }),
      media: Array.from(content.querySelectorAll('figure')).map(frame => {
        const parent = frame.parentElement!;
        const rect = frame.getBoundingClientRect();
        return { width: rect.width, height: rect.height, column: getComputedStyle(parent).gridColumn, fit: getComputedStyle(frame.querySelector('img')!).objectFit };
      }),
      outOfBounds: rects.filter(rect => rect.left < box.left - 1 || rect.right > box.right + 1 || rect.top < box.top - 1 || rect.bottom > box.bottom + 1).length,
      collisions: collisions.length,
    };
  });
}

// Scripted offline fixtures, using the same MockLLMProvider path as generation.
for (const paper of ['A4', 'LETTER'] as const) for (const review of reviews) {
  test(`${review.direction} ${review.id} ${paper}: A/B physical canvas, draft, print and searchable PDF`, async ({ page, request }) => {
    test.setTimeout(180_000);
    // Give both physical sheets room; the authoring workspace itself is not the fixture.
    await page.setViewportSize({ width: 2200, height: 1400 });
    const fixture = corpus.scenarios.find(item => item.id === review.id)!;
    const signatures: Awaited<ReturnType<typeof geometry>>[] = [];
    const screenshots: Buffer[] = [];
    for (const [index, option] of (['option_a', 'option_b'] as const).entries()) {
      const created = await request.post(api, { data: { context: { ...fixture.book_context, direction: review.direction, page_size: paper } } });
      expect(created.status()).toBe(201);
      const sid = (await created.json()).session_id;
      const asset_ids: string[] = [];
      for (const id of fixture.assets) {
        const asset = corpus.assets[id];
        const upload = await request.post(`${api}/${sid}/assets`, { multipart: { files: { name: basename(asset.path), mimeType: asset.mime_type, buffer: readFileSync(resolve(examples, asset.path)) } } });
        expect(upload.status()).toBe(201);
        asset_ids.push((await upload.json()).assets[0].asset_id);
      }
      const generated = await request.post(`${api}/${sid}/pages`, { data: { text: fixture.copy, asset_ids } });
      expect(generated.status()).toBe(201);
      const result = await generated.json() as S['PageGenerationResult'];
      expect(result[option].composition).toBe(review.composition);
      await page.goto(`/sessions/${sid}`);
      await page.addStyleTag({ content: '.studio { max-width: none; }' });
      const preview = page.locator('.option-card .page-canvas').nth(index);
      const before = await geometry(preview);
      signatures.push(before);
      expect(before.width).toBeCloseTo(paper === 'A4' ? 210 / 25.4 * 96 : 816, 0);
      expect(before.height).toBeCloseTo(paper === 'A4' ? 297 / 25.4 * 96 : 1056, 0);
      expect(before.outOfBounds).toBe(0);
      expect(before.collisions).toBe(0);
      expect(before.heading.margin).toBe('0px');
      if (review.composition === 'opener') expect(parseFloat(before.heading.size)).toBeGreaterThan(index ? 28 : 44);
      if (review.composition === 'comparison') {
        expect(before.media.map(item => item.column)).toEqual(['1 / 7', '7 / -1']);
        const frames = await preview.locator('figure').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().top));
        expect(frames[0]).toBeCloseTo(frames[1], 1);
      }
      if (review.composition === 'portrait_story') {
        expect(before.media[0].column).toBe(index ? '9 / -1' : '1 / 5');
        expect(parseFloat(before.quoteSize!)).toBeGreaterThan(index ? 20 : 27);
      }
      for (const image of await preview.locator('[data-protected-media="true"] img').all()) {
        await expect(image).toHaveCSS('object-fit', 'contain');
        await expect(image.locator('xpath=ancestor::figure').locator('[data-scrim]')).toHaveCount(0);
      }
      screenshots.push(await preview.screenshot({ animations: 'disabled', path: test.info().outputPath(`${review.id}-${paper}-${option}.png`) }));
      await request.post(`${api}/${sid}/pages/${result.page_id}/selection`, { data: { option_id: option } });
      await page.goto(`/sessions/${sid}`);
      const draft = page.locator('.draft-viewer .page-canvas');
      const drafted = await geometry(draft);
      expect(drafted.heading).toEqual(before.heading);
      expect(drafted.media).toEqual(before.media);
      expect(drafted.paints).toEqual(before.paints);
      await page.goto(`/print/${sid}`);
      await expect(page.locator('html')).toHaveAttribute('data-print-ready', 'true');
      const printed = page.locator('.print-page[data-kind="body"] .page-canvas');
      const printGeometry = await geometry(printed);
      expect(printGeometry.heading).toEqual(before.heading);
      expect(printGeometry.media).toEqual(before.media);
      expect(printGeometry.paints).toEqual(before.paints);
      expect(printGeometry.outOfBounds).toBe(0);
      expect(printGeometry.collisions).toBe(0);
      await page.emulateMedia({ media: 'print' });
      const screenshot = await printed.screenshot({ animations: 'disabled' });
      const exported = await request.post(`${api}/${sid}/export`, { data: {}, timeout: 120_000 });
      if (exported.status() !== 200) {
        const diagnostic = spawnSync(python, ['-c', 'import sys,io; from pypdf import PdfReader; print("\\n".join(page.extract_text() for page in PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages))'], { input: await page.pdf({ preferCSSPageSize: true, printBackground: true }), encoding: 'utf8' });
        expect(exported.status(), `${await exported.text()}\nDirect browser PDF text: ${diagnostic.stdout}`).toBe(200);
      }
      const verified = spawnSync(python, ['-c', [
        'import base64,io,json,sys,pymupdf',
        'from PIL import Image,ImageColor',
        'from pypdf import PdfReader',
        'from bookgen.config import load_settings',
        'from bookgen.adapters.pdf.playwright_exporter import image_ssim',
        'from bookgen.domain.theme import contrast_ratio',
        'payload=json.load(sys.stdin); data=base64.b64decode(payload["pdf"]); reader=PdfReader(io.BytesIO(data))',
        'assert len(reader.pages)==3',
        'text=" ".join(reader.pages[-1].extract_text().split())',
        'assert all(" ".join(value.split()) in text for value in payload["text"])',
        'settings=load_settings(); color=lambda value: "#"+"".join(f"{channel:02X}" for channel in ImageColor.getrgb(value))',
        'ratios=[contrast_ratio(color(paint["foreground"]),color(paint["background"])) for paint in payload["paints"]]',
        'assert min(ratios)>=settings.theme.contrast_min_ratio,(ratios,settings.theme.contrast_min_ratio)',
        'raster=pymupdf.open(stream=data,filetype="pdf"); pix=raster[-1].get_pixmap(matrix=pymupdf.Matrix(96/72,96/72),alpha=False)',
        'actual=Image.frombytes("RGB",(pix.width,pix.height),pix.samples); expected=Image.open(io.BytesIO(base64.b64decode(payload["png"])))',
        'score=image_ssim(expected,actual.resize(expected.size)); minimum=settings.export.min_ssim',
        'assert score>=minimum,(score,minimum)',
        'print(json.dumps({"page_count":len(reader.pages),"ssim":score,"minimum":minimum,"minimum_contrast":min(ratios)}))',
      ].join('\n')], { input: JSON.stringify({ pdf: (await exported.body()).toString('base64'), png: screenshot.toString('base64'), text: result.input_blocks.map(block => block.text), paints: before.paints }), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve('../api/src') } });
      expect(verified.status, verified.stderr).toBe(0);
      await test.info().attach(`${review.id}-${paper}-${option}-pdf-gate`, { body: verified.stdout, contentType: 'application/json' });
      await page.emulateMedia({ media: 'screen' });
    }
    expect(signatures[0].heading.size === signatures[1].heading.size && signatures[0].quoteSize === signatures[1].quoteSize && signatures[0].media[0].column === signatures[1].media[0].column).toBe(false);
    // Portable bundled-font baselines use the same configured SSIM gate as PDF.
    // Both options pass physical-size, parity and PDF review before recording.
    const baselinePairs = screenshots.map((screenshot, index) => {
      const path = resolve(test.info().snapshotDir, `${review.id}-${paper}-option-${index ? 'b' : 'a'}.png`);
      if (['all', 'changed'].includes(test.info().config.updateSnapshots)) {
        mkdirSync(test.info().snapshotDir, { recursive: true });
        writeFileSync(path, screenshot);
      }
      expect(existsSync(path), `Missing reviewed physical baseline: ${path}`).toBe(true);
      return [screenshot.toString('base64'), readFileSync(path).toString('base64')];
    });
    const compared = spawnSync(python, ['-c', [
      'import base64,io,json,sys',
      'from PIL import Image',
      'from bookgen.config import load_settings',
      'from bookgen.adapters.pdf.playwright_exporter import image_ssim',
      'pairs=json.load(sys.stdin); minimum=load_settings().export.min_ssim',
      'scores=[image_ssim(*(Image.open(io.BytesIO(base64.b64decode(value))) for value in pair)) for pair in pairs]',
      'assert min(scores)>=minimum,(scores,minimum)',
      'print(json.dumps({"baseline_ssim":scores,"minimum":minimum}))',
    ].join('\n')], { input: JSON.stringify(baselinePairs), encoding: 'utf8', env: { ...process.env, PYTHONPATH: resolve('../api/src') } });
    expect(compared.status, compared.stderr).toBe(0);
    await test.info().attach(`${review.id}-${paper}-baseline-gate`, { body: compared.stdout, contentType: 'application/json' });
  });
}
