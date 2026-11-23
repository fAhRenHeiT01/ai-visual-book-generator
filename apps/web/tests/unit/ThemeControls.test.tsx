import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { ThemeControls } from '../../src/components/setup/ThemeControls';
import { sessionApi } from '../../src/lib/sessionApi';
import type { components } from '../../src/types/generated';

type S = components['schemas'];
vi.mock('../../src/lib/sessionApi', () => ({ sessionApi: { saveAppearance: vi.fn(), extractTheme: vi.fn() } }));
const appearance: S['AppearanceResponse'] = { status: 'unavailable', tokens: { theme_id: 'default', palette_source: 'preset', color_paper: '#FFFFFF', color_ink_primary: '#111827', color_ink_muted: '#4B5563', color_brand_primary: '#1D4ED8', color_brand_accent: '#0EA5E9', color_surface_tint: '#F3F4F6', font_heading: 'Inter', font_body: 'Source Serif 4', radius_px: 6, page_margin_mm: 16, chrome_band_mm: 12 }, chrome: { enabled: true, header_left: '', header_right: '{chapter_title}', footer_left: '', footer_center: '', footer_right: 'Page {page_number} of {total_pages}', suppress_on_archetypes: ['full_bleed_hero', 'section_divider'] } };
afterEach(() => { cleanup(); vi.resetAllMocks(); });

test('preset selection and manual swatches save through the session appearance API', async () => {
  vi.mocked(sessionApi.saveAppearance).mockImplementation(async (_id, value) => ({ ...value, status: 'unavailable' }));
  const onAppearanceChange = vi.fn();
  const view = render(<ThemeControls sessionId="s1" appearance={appearance} onAppearanceChange={onAppearanceChange} />);
  fireEvent.change(screen.getByLabelText('Palette preset'), { target: { value: 'ocean' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save appearance' }));
  await waitFor(() => expect(onAppearanceChange).toHaveBeenCalledOnce());
  expect(sessionApi.saveAppearance).toHaveBeenLastCalledWith('s1', expect.objectContaining({ tokens: expect.objectContaining({ theme_id: 'ocean', palette_source: 'preset' }) }));
  fireEvent.change(screen.getByLabelText('Brand primary'), { target: { value: '#123456' } });
  fireEvent.change(screen.getByLabelText('Footer center'), { target: { value: 'Copyright 2026 Example' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save appearance' }));
  await waitFor(() => expect(onAppearanceChange).toHaveBeenCalledTimes(2));
  const saved = onAppearanceChange.mock.calls[1][0] as S['AppearanceResponse'];
  view.unmount();
  render(<ThemeControls sessionId="s1" appearance={saved} />);
  expect((screen.getByLabelText('Brand primary') as HTMLInputElement).value).toBe('#123456');
  expect((screen.getByLabelText('Footer center') as HTMLInputElement).value).toBe('Copyright 2026 Example');
});

test('extraction failure is actionable; successful extraction can be saved', async () => {
  vi.mocked(sessionApi.extractTheme).mockResolvedValueOnce({ status: 'unavailable', tokens: null }).mockResolvedValueOnce({ status: 'available', tokens: { ...appearance.tokens, palette_source: 'website_extracted', color_brand_primary: '#123456' } });
  render(<ThemeControls sessionId="s1" appearance={appearance} />);
  fireEvent.change(screen.getByLabelText('Website URL'), { target: { value: 'https://brand.example' } });
  fireEvent.click(screen.getByRole('button', { name: 'Extract website theme' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Extract website theme' }));
  await waitFor(() => expect((screen.getByLabelText('Brand primary') as HTMLInputElement).value).toBe('#123456'));
});

test('approved appearance locks all edits when generation starts', () => {
  render(<ThemeControls sessionId="s1" appearance={appearance} locked />);
  for (const control of screen.getAllByRole('button')) expect((control as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText('Brand primary') as HTMLInputElement).disabled).toBe(true);
});
