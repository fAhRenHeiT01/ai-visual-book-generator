import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

test('three pages persist, pending review reloads, and print contains only ordered draft pages', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Book title (optional)').fill('Three page review');
  await page.getByRole('button', { name: 'Create book' }).click();
  await expect(page).toHaveURL(/\/sessions\//);
  const sessionId = page.url().split('/').at(-1)!;
  let commits = 0;
  page.on('request', req => { if (req.url().endsWith('/selection') && req.method() === 'POST') commits++; });
  for (let number = 1; number <= 3; number++) {
    await page.getByLabel('Page text').fill(`Page ${number} original copy.\n\nSupporting paragraph ${number}.`);
    await page.getByLabel('Page images').setInputFiles({ name: 'chart.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFUlEQVR4nGP8//8/AyHARFDFsFcEAHkjAw3jrppVAAAAAElFTkSuQmCC', 'base64') });
    await page.getByRole('button', { name: 'Generate options' }).click();
    await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
    const options = page.locator('.option-card');
    expect(await options.nth(0).getAttribute('data-archetype')).not.toBe(await options.nth(1).getAttribute('data-archetype'));
    await expect(options.nth(0).locator('.rationale')).not.toBeEmpty();
    await expect(options.nth(1).locator('.rationale')).not.toBeEmpty();
    if (number === 2) { await page.reload(); await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible(); }
    if (number === 1) { await page.keyboard.press('2'); await page.keyboard.press('Enter'); }
    else { await page.getByRole('radio', { name: /Option A/ }).click(); await page.getByRole('button', { name: 'Confirm selection' }).click(); }
    await expect(page.getByText(`${number} committed page${number === 1 ? '' : 's'}`, { exact: true })).toBeVisible();
  }
  expect(commits).toBe(3);
  await page.reload();
  const draft = page.locator('.draft-viewer [data-testid="page-canvas"]');
  await expect(draft).toHaveCount(3);
  const snapshot = await request.get(`http://127.0.0.1:8007/api/v1/sessions/${sessionId}`);
  expect((await snapshot.json()).committed_pages.map((p: { page_number: number }) => p.page_number)).toEqual([1, 2, 3]);
  await page.emulateMedia({ media: 'print' });
  await expect(page.getByRole('button', { name: 'Generate options' })).toBeHidden();
  await expect(draft.nth(0)).toBeVisible();
  const pdf = await page.pdf({ preferCSSPageSize: true });
  const python = process.env.PYTHON ?? resolve('../..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const printed = spawnSync(python, ['-c', 'from pypdf import PdfReader; import io,sys; r=PdfReader(io.BytesIO(sys.stdin.buffer.read())); print(len(r.pages)); print("\\n".join(p.extract_text() for p in r.pages))'], { input: pdf, encoding: 'utf8' });
  expect(printed.status).toBe(0);
  expect(printed.stdout.split('\n')[0].trim()).toBe('3');
  expect(printed.stdout).toContain('Page 1 original copy.');
  expect(printed.stdout).toContain('Page 2 original copy.');
  expect(printed.stdout).toContain('Page 3 original copy.');
  expect(printed.stdout).not.toContain('Generate options');
  expect(errors).toEqual([]);
});
