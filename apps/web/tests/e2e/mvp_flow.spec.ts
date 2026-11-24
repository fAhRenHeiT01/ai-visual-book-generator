import { expect, test } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

test('normalized copy keeps separate explicit and inferred chapter titles in Studio and print', async ({ page, request }) => {
  const api = 'http://127.0.0.1:8007/api/v1/sessions';
  const session = await (await request.post(api, { data: { context: { title: 'Book context title' } } })).json();
  const prefix = `${api}/${session.session_id}`;
  const appearance = await (await request.get(`${prefix}/appearance`)).json();
  expect((await request.put(`${prefix}/appearance`, { data: { tokens: appearance.tokens,
    chrome: { ...appearance.chrome, suppress_on_archetypes: [] } } })).status()).toBe(200);
  const inferred = await (await request.post(`${prefix}/pages`, { data: { text: '# Opening title\nBody\tcopy.' } })).json();
  expect(inferred.title).toBe('Opening title');
  expect(inferred.input_blocks.map((block: { text: string }) => block.text)).toEqual(['# Opening title Body copy.']);
  await request.post(`${prefix}/pages/${inferred.page_id}/selection`, { data: { option_id: 'option_a' } });
  await page.goto(`/sessions/${session.session_id}`);
  await page.getByLabel('Page title (optional)').fill('Explicit chapter');
  await page.getByLabel('Page text').fill('# Different source heading\\nBody\\tcopy.');
  await page.getByRole('button', { name: 'Generate options' }).click();
  await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
  const snapshot = await (await request.get(prefix)).json();
  expect(snapshot.pending_review.title).toBe('Explicit chapter');
  expect(snapshot.pending_review.input_blocks.map((block: { text: string }) => block.text)).toEqual(['# Different source heading Body copy.']);
  await page.getByRole('button', { name: 'Confirm selection' }).click();
  await expect(page.getByText('2 committed pages', { exact: true })).toBeVisible();
  const draftHeaders = page.locator('.draft-pages .master-chrome.chrome-header');
  await expect(draftHeaders).toHaveText(['Opening title', 'Explicit chapter']);
  await page.evaluate(() => { window.print = () => {}; });
  await page.getByRole('button', { name: 'Print draft' }).click();
  await expect(page.locator('#compliance-print .master-chrome.chrome-header')).toHaveText(['Opening title', 'Explicit chapter']);
  await page.goto(`/print/${session.session_id}`);
  await expect.poll(() => page.locator('html').getAttribute('data-print-ready')).toBe('true');
  await expect(page.locator('[data-kind="body"] .master-chrome.chrome-header')).toHaveText(['Opening title', 'Explicit chapter']);
  const manifest = await (await request.get(`${prefix}/print-data`)).json();
  expect(manifest.pages.filter((item: { kind: string }) => item.kind === 'body').map((item: { title: string; chapter_title: string }) => [item.title, item.chapter_title])).toEqual([
    ['Opening title', 'Opening title'], ['Explicit chapter', 'Explicit chapter'],
  ]);
});

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

test('refresh recovers uploaded input and a lost generation response with one durable page', async ({ page, request }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Create book' }).click();
  await expect(page).toHaveURL(/\/sessions\//);
  const sessionId = page.url().split('/').at(-1)!;
  let uploads = 0;
  const attempts: { page_id: string; asset_ids: string[] }[] = [];
  page.on('request', req => { if (req.url().endsWith('/assets') && req.method() === 'POST') uploads++; });
  let interrupted = false;
  await page.route('**/api/v1/sessions/*/pages', async route => {
    attempts.push(route.request().postDataJSON());
    if (!interrupted) { interrupted = true; await route.abort('failed'); return; }
    // The retry reaches review on the server, then its response is lost.
    await route.fetch();
    await route.abort('failed');
  });
  await page.getByLabel('Page text').fill('Durable original copy.');
  await page.getByLabel('Page images').setInputFiles({ name: 'chart.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFUlEQVR4nGP8//8/AyHARFDFsFcEAHkjAw3jrppVAAAAAElFTkSuQmCC', 'base64') });
  await page.getByRole('button', { name: 'Generate options' }).click();
  await expect(page.locator('.studio [role="alert"]')).toBeVisible();
  expect(attempts).toHaveLength(1);
  expect(await page.evaluate(() => Object.values(localStorage))).toContainEqual(expect.stringContaining('Durable original copy.'));
  await page.reload();
  await expect(page.getByLabel('Page text')).toHaveValue('Durable original copy.');
  await page.getByRole('button', { name: 'Retry generation' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[0].page_id).toBe(attempts[1].page_id);
  expect(attempts[0].asset_ids).toEqual(attempts[1].asset_ids);
  expect(uploads).toBe(1);
  await page.reload();
  await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
  expect(attempts).toHaveLength(2);
  await page.getByRole('button', { name: 'Confirm selection' }).click();
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
  const snapshot = await request.get(`http://127.0.0.1:8007/api/v1/sessions/${sessionId}`);
  const saved = await snapshot.json();
  expect(saved.committed_pages).toHaveLength(1);
  expect(saved.current_page_index).toBe(2);
});

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`complete A/B review fits the workspace at ${viewport.width}px without horizontal scrolling`, async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(viewport);
    await page.goto('/');
    await page.getByLabel('Book direction').selectOption('consulting_report');
    const create = page.getByRole('button', { name: 'Create book' });
    if (viewport.width < 1000) { await create.focus(); await page.keyboard.press('Enter'); }
    else await create.click();
    await expect(page).toHaveURL(/\/sessions\//);
    const sessionId = page.url().split('/').at(-1)!;
    const created = await (await request.get(`http://127.0.0.1:8007/api/v1/sessions/${sessionId}`)).json();
    expect(created.context.direction).toBe('consulting_report');
    await expect(page.getByRole('button', { name: 'Download PDF' })).toBeDisabled();
    await page.getByLabel('Page text').fill('A complete page preview.\n\nOriginal supporting copy stays on the physical page.');
    await page.getByRole('button', { name: 'Generate options' }).click();
    const options = page.locator('.option-card');
    await expect(options).toHaveCount(2);
    for (const option of await options.all()) {
      const canvas = option.getByTestId('page-canvas');
      await expect(canvas).toHaveAttribute('data-settled', 'true');
      await expect.poll(async () => canvas.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        const wrapper = element.closest('.canvas-scroll')!;
        const frame = wrapper.getBoundingClientRect();
        return bounds.width <= frame.width + 1 && bounds.height <= frame.height + 1 && wrapper.scrollWidth <= wrapper.clientWidth + 1;
      })).toBe(true);
      expect(await canvas.evaluate(element => element.clientWidth)).toBeGreaterThan(790);
    }
    const boxes = await options.evaluateAll(elements => elements.map(element => {
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y };
    }));
    if (viewport.width > 1000) expect(boxes[0].y).toBe(boxes[1].y);
    else expect(boxes[1].y).toBeGreaterThan(boxes[0].y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const appearance = page.getByText('Book appearance', { exact: true });
    await appearance.focus(); await page.keyboard.press('Enter');
    await expect(page.getByText('Appearance is locked because page 1 creation has started.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save appearance' })).toBeDisabled();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('link', { name: /Reopen this book/ })).toHaveCount(0);
    await page.getByRole('link', { name: 'Visual Book Generator', exact: true }).click();
    const reopen = page.locator(`a[href="/sessions/${sessionId}"]`);
    await expect(reopen).toBeVisible();
    await reopen.focus();
    await Promise.all([page.waitForEvent('load'), page.keyboard.press('Enter')]);
    await expect(page.getByRole('radio', { name: /Option A/ })).toBeVisible();
    await page.getByRole('radio', { name: /Option A/ }).focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('radio', { name: /Option B/ })).toBeFocused();
    await expect(page.getByRole('radio', { name: /Option B/ })).toHaveAttribute('aria-checked', 'true');
    if (viewport.width < 1000) { await page.keyboard.press('Tab'); await page.keyboard.press('Enter'); }
    else await page.getByRole('button', { name: 'Confirm selection' }).click();
    await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'Page 1', exact: true }).click();
    await expect(page.locator('.draft-page .page-canvas')).toBeVisible();
    const download = page.waitForEvent('download');
    const exportButton = page.getByRole('button', { name: 'Download PDF' });
    await expect(exportButton).toBeEnabled();
    if (viewport.width < 1000) { await exportButton.focus(); await page.keyboard.press('Enter'); }
    else await exportButton.click();
    expect((await download).suggestedFilename()).toBe('book.pdf');
    await expect(exportButton).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test('home resumes saved pages and confirms complete deletion with retry on a narrow screen', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const api = 'http://127.0.0.1:8007/api/v1/sessions';
  const saved = await (await request.post(api, { data: { context: { title: 'A saved book' } } })).json();
  const other = await (await request.post(api, { data: { context: { title: 'Another saved book' } } })).json();
  const sid = saved.session_id;
  const generated = await (await request.post(`${api}/${sid}/pages`, { data: { text: 'Original committed copy.' } })).json();
  await request.post(`${api}/${sid}/pages/${generated.page_id}/selection`, { data: { option_id: 'option_a' } });
  const loaded: string[] = [];
  page.on('request', req => { if (req.method() === 'GET' && [api + '/' + sid, api + '/' + other.session_id].includes(req.url())) loaded.push(req.url()); });
  await page.goto('/');
  await page.evaluate(({ sid, otherId }) => {
    localStorage.setItem(`bookgen:active-page:${sid}`, JSON.stringify({ page_id: 'saved-draft', page_number: 2, text: 'Saved next-page copy.', asset_ids: [] }));
    localStorage.setItem(`bookgen:active-page:${otherId}`, 'other saved draft');
  }, { sid, otherId: other.session_id });
  const row = page.getByRole('listitem').filter({ has: page.getByRole('heading', { name: 'A saved book', exact: true }) });
  await expect(row).toContainText('1 committed page');
  await expect(row).toContainText('Next page 2');
  expect(loaded).toEqual([]);
  const summary = await (await request.get(api)).json();
  expect(summary.sessions.find((entry: { session_id: string }) => entry.session_id === sid)).not.toHaveProperty('committed_pages');
  await row.getByRole('link', { name: 'Reopen this book: A saved book' }).click();
  await expect(page).toHaveURL(`/sessions/${sid}`);
  await expect(page.getByLabel('Page text')).toHaveValue('Saved next-page copy.');
  await expect(page.getByText('1 committed page', { exact: true })).toBeVisible();
  await expect(page.locator('.examples')).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Reopen this book/ })).toHaveCount(0);
  await page.getByRole('link', { name: 'Visual Book Generator', exact: true }).click();
  await row.getByRole('button', { name: 'Delete A saved book' }).click();
  await expect(page.getByRole('dialog', { name: 'Delete A saved book?' })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect((await request.get(`${api}/${sid}`)).status()).toBe(200);
  let failDelete = true;
  await page.route(`${api}/${sid}`, async route => {
    if (route.request().method() === 'DELETE' && failDelete) {
      failDelete = false;
      await route.fulfill({ status: 503, headers: { 'access-control-allow-origin': 'http://127.0.0.1:3007' }, json: { detail: 'Retry deleting this book' } });
    } else await route.continue();
  });
  await row.getByRole('button', { name: 'Delete A saved book' }).click();
  await page.getByRole('button', { name: 'Permanently delete book' }).click();
  await expect(page.locator('.studio [role="alert"]')).toContainText('Retry deleting this book');
  await expect(row).toBeVisible();
  await page.getByRole('button', { name: 'Permanently delete book' }).click();
  await expect(row).toHaveCount(0);
  expect((await request.get(`${api}/${sid}`)).status()).toBe(404);
  expect((await request.get(`${api}/${other.session_id}`)).status()).toBe(200);
  expect(await page.evaluate(id => localStorage.getItem(`bookgen:active-page:${id}`), sid)).toBeNull();
  expect(await page.evaluate(id => localStorage.getItem(`bookgen:active-page:${id}`), other.session_id)).toBe('other saved draft');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.goto(`/sessions/${sid}`);
  await expect(page.locator('.studio [role="alert"]')).toContainText('Session not found');
  await expect(page.getByRole('button', { name: 'Retry loading book' })).toBeVisible();
});
