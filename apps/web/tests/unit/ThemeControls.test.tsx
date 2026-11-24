import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { ThemeControls } from '../../src/components/setup/ThemeControls';
import type { components } from '../../src/types/generated';

type S = components['schemas'];
const appearance: S['AppearanceResponse'] = { status: 'available', tokens: { theme_id: 'default', palette_source: 'preset', color_paper: '#FFFFFF', color_ink_primary: '#111827', color_ink_muted: '#4B5563', color_brand_primary: '#1D4ED8', color_brand_accent: '#0369A1', color_surface_tint: '#F3F4F6', font_heading: 'Inter', font_body: 'Source Serif 4', radius_px: 6, page_margin_mm: 16, chrome_band_mm: 12 }, chrome: { enabled: true, header_left: '', header_right: '{chapter_title}', footer_left: '', footer_center: '', footer_right: 'Page {page_number} of {total_pages}', suppress_on_archetypes: ['full_bleed_hero', 'section_divider'] } };
const preset: S['ThemeLibraryEntry'] = { theme_id: 'default', name: 'Default', tokens: appearance.tokens };
const ocean: S['ThemeLibraryEntry'] = { theme_id: 'ocean', name: 'Ocean', tokens: { ...appearance.tokens, theme_id: 'ocean', color_brand_primary: '#164E63' } };
const extracted: S['ThemeLibraryEntry'] = { theme_id: 'saved-brand', name: 'Example brand', source_url: 'https://brand.example/', tokens: { ...appearance.tokens, palette_source: 'website_extracted', color_brand_primary: '#123456' } };
function api() {
  const themes = [preset, ocean];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith('/themes')) return Response.json({ themes });
    if (path.endsWith('/extract')) {
      themes.push(extracted);
      return Response.json({ status: 'available', tokens: extracted.tokens, theme_id: extracted.theme_id });
    }
    if (path.endsWith('/appearance/theme')) return Response.json({ ...appearance, tokens: themes.find(theme => theme.theme_id === JSON.parse(init!.body as string).theme_id)!.tokens });
    if (path.endsWith('/appearance')) return Response.json({ ...JSON.parse(init!.body as string), status: 'available' });
    throw new Error(`Unexpected fetch: ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('extraction persists a named palette that another session can inspect and select by keyboard before applying', async () => {
  const fetcher = api();
  const onAppearanceChange = vi.fn();
  const first = render(<ThemeControls sessionId="first" appearance={appearance} onAppearanceChange={onAppearanceChange} />);
  await screen.findByRole('radio', { name: 'Default' });
  fireEvent.change(screen.getByLabelText('Theme name (optional)'), { target: { value: 'Example brand' } });
  fireEvent.change(screen.getByLabelText('Website URL'), { target: { value: 'https://brand.example/' } });
  fireEvent.click(screen.getByRole('button', { name: 'Extract website theme' }));
  await screen.findByText('Theme saved to library. Inspect the preview, then apply it to this book.');
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/themes/extract'), expect.objectContaining({ body: JSON.stringify({ url: 'https://brand.example/', name: 'Example brand' }) }));
  expect(onAppearanceChange).not.toHaveBeenCalled();
  first.unmount();
  render(<ThemeControls sessionId="second" appearance={appearance} onAppearanceChange={onAppearanceChange} />);
  const defaultCard = await screen.findByRole('radio', { name: 'Default' });
  defaultCard.focus();
  fireEvent.keyDown(defaultCard, { key: 'End' });
  const savedCard = screen.getByRole('radio', { name: 'Example brand' });
  expect(document.activeElement).toBe(savedCard);
  expect(savedCard.getAttribute('aria-checked')).toBe('true');
  expect((screen.getByLabelText('Brand primary') as HTMLInputElement).value).toBe('#123456');
  expect(screen.getByTestId('page-canvas').style.getPropertyValue('--color-brand-primary')).toBe('#123456');
  expect(screen.getByRole('img', { name: 'Brand primary swatch: #123456' })).toBeDefined();
  expect(onAppearanceChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Apply theme' }));
  await waitFor(() => expect(onAppearanceChange).toHaveBeenCalledOnce());
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/second/appearance/theme'), expect.objectContaining({ body: JSON.stringify({ theme_id: 'saved-brand' }) }));
});

test('a role edit preserves all other tokens and chrome, rejects invalid hex, and applies only on save', async () => {
  const fetcher = api();
  const onAppearanceChange = vi.fn();
  render(<ThemeControls sessionId="s1" appearance={appearance} onAppearanceChange={onAppearanceChange} />);
  await screen.findByRole('radio', { name: 'Ocean' });
  fireEvent.change(screen.getByLabelText('Footer center'), { target: { value: 'Copyright Example' } });
  fireEvent.change(screen.getByLabelText('Brand primary'), { target: { value: '#bad' } });
  expect(screen.getByLabelText('Brand primary').getAttribute('aria-invalid')).toBe('true');
  expect(screen.getByRole('alert').textContent).toContain('six hexadecimal digits');
  expect((screen.getByRole('button', { name: 'Apply theme' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByTestId('page-canvas').style.getPropertyValue('--color-brand-primary')).toBe(appearance.tokens.color_brand_primary);
  fireEvent.change(screen.getByLabelText('Brand primary'), { target: { value: '#123456' } });
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByText(/Primary ink on paper:/).textContent).toContain(':1');
  expect(onAppearanceChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Apply theme' }));
  await screen.findByText('Appearance saved. Colors were checked for readable contrast.');
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/s1/appearance'), expect.objectContaining({ method: 'PUT', body: JSON.stringify({ tokens: { ...appearance.tokens, color_brand_primary: '#123456', palette_source: 'manual' }, chrome: { ...appearance.chrome, footer_center: 'Copyright Example' } }) }));
  expect(onAppearanceChange).toHaveBeenCalledOnce();
});

test('extraction progress, errors, and retry keep the book unchanged until explicit apply', async () => {
  const fetcher = api();
  let finish!: (response: Response) => void;
  fetcher.mockImplementationOnce(async () => Response.json({ themes: [preset] }));
  const changed = vi.fn();
  render(<ThemeControls sessionId="s1" appearance={appearance} onAppearanceChange={changed} />);
  await screen.findByRole('radio', { name: 'Default' });
  fetcher.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  fireEvent.change(screen.getByLabelText('Website URL'), { target: { value: 'https://brand.example/' } });
  fireEvent.click(screen.getByRole('button', { name: 'Extract website theme' }));
  expect(screen.getByRole('status').textContent).toBe('Extracting website theme...');
  expect((screen.getByRole('button', { name: 'Extract website theme' }) as HTMLButtonElement).disabled).toBe(true);
  finish(Response.json({ status: 'unavailable', tokens: null }));
  expect((await screen.findByRole('alert')).textContent).toContain('Choose a theme or try another website');
  fireEvent.click(screen.getByRole('button', { name: 'Extract website theme' }));
  await screen.findByText('Theme saved to library. Inspect the preview, then apply it to this book.');
  expect(screen.queryByRole('alert')).toBeNull();
  expect(changed).not.toHaveBeenCalled();
});

test('library and apply failures can be retried without discarding the draft', async () => {
  const fetcher = api();
  fetcher.mockResolvedValueOnce(Response.json({ detail: 'Library unavailable' }, { status: 503 }));
  render(<ThemeControls sessionId="s1" appearance={appearance} />);
  expect((await screen.findByRole('alert')).textContent).toContain('Library unavailable');
  fireEvent.click(screen.getByRole('button', { name: 'Retry theme library' }));
  fireEvent.click(await screen.findByRole('radio', { name: 'Ocean' }));
  fetcher.mockResolvedValueOnce(Response.json({ detail: 'Please retry appearance' }, { status: 503 }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply theme' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Please retry appearance');
  expect((screen.getByLabelText('Brand primary') as HTMLInputElement).value).toBe('#164E63');
  fireEvent.click(screen.getByRole('button', { name: 'Apply theme' }));
  await screen.findByText('Appearance saved. Colors were checked for readable contrast.');
});

test('locking discards an unapplied draft and exposes the current appearance read-only', async () => {
  api();
  const view = render(<ThemeControls sessionId="s1" appearance={appearance} />);
  fireEvent.click(await screen.findByRole('radio', { name: 'Ocean' }));
  view.rerender(<ThemeControls sessionId="s1" appearance={appearance} locked />);
  expect(screen.getByText('Appearance is locked for this book.')).toBeDefined();
  for (const button of screen.getAllByRole('button')) expect((button as HTMLButtonElement).disabled).toBe(true);
  for (const input of screen.getAllByRole('textbox')) expect(input.matches(':disabled')).toBe(true);
  for (const radio of screen.getAllByRole('radio')) expect((radio as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByTestId('page-canvas').style.getPropertyValue('--color-brand-primary')).toBe(appearance.tokens.color_brand_primary);
});


test('an incomplete appearance cannot crash the surrounding workspace while tokens are loading', async () => {
  api();
  const incomplete = structuredClone(appearance);
  Reflect.deleteProperty(incomplete.tokens, 'color_paper');
  const view = render(<ThemeControls sessionId="s1" appearance={incomplete} />);
  expect(screen.queryByTestId('page-canvas')).toBeNull();
  view.rerender(<ThemeControls sessionId="s1" appearance={appearance} />);
  await screen.findByTestId('page-canvas');
});


test('theme cards use one tab stop and arrow navigation retains chrome edits', async () => {
  api();
  render(<ThemeControls sessionId="s1" appearance={appearance} />);
  const first = await screen.findByRole('radio', { name: 'Default' });
  const second = screen.getByRole('radio', { name: 'Ocean' });
  expect(first.tabIndex).toBe(0);
  expect(second.tabIndex).toBe(-1);
  fireEvent.change(screen.getByLabelText('Header left'), { target: { value: 'Brand heading' } });
  first.focus();
  for (const key of ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home']) fireEvent.keyDown(document.activeElement!, { key });
  expect(document.activeElement).toBe(first);
  fireEvent.keyDown(first, { key: 'ArrowRight' });
  expect(document.activeElement).toBe(second);
  expect(first.tabIndex).toBe(-1);
  expect(second.tabIndex).toBe(0);
  expect((screen.getByLabelText('Header left') as HTMLInputElement).value).toBe('Brand heading');
  for (const label of ['Paper', 'Primary ink', 'Muted ink', 'Brand primary', 'Brand accent', 'Surface tint']) {
    expect(screen.getAllByRole('img').find(element => element.getAttribute('aria-label')?.startsWith(`${label} swatch:`))).toBeDefined();
  }
});
