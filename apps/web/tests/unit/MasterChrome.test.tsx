import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { PageCanvas } from '../../src/engine/PageCanvas';
import { MasterChrome } from '../../src/engine/MasterChrome';
import type { components } from '../../src/types/generated';

type S = components['schemas'];
const tokens: S['DesignTokens'] = { theme_id: 'test', palette_source: 'manual', color_paper: '#FFFFFF', color_ink_primary: '#111827', color_ink_muted: '#4B5563', color_brand_primary: '#123456', color_brand_accent: '#654321', color_surface_tint: '#EEEEEE', font_heading: 'Inter', font_body: 'Georgia', radius_px: 6, page_margin_mm: 16, chrome_band_mm: 12 };
const config: S['MasterChromeConfig'] = { enabled: true, header_left: 'Annual review', header_right: '{chapter_title}', footer_left: 'Copyright 2026 Company', footer_center: 'Private', footer_right: 'Page {page_number} of {total_pages}', suppress_on_archetypes: ['full_bleed_hero', 'section_divider'] };
const layout: S['PageLayoutAST'] = { option_id: 'option_a', archetype: 'minimalist_swiss', rationale: '', strategy_tag: '', density_scale: 'normal', column_count: 1, components: [], surface_role: 'paper' };
const result: S['PageGenerationResult'] = { page_id: 'p1', page_number: 2, title: null, input_blocks: [], input_assets: [], option_a: layout, option_b: { ...layout, option_id: 'option_b' }, selected_option_id: 'option_a', metrics_ledger: [], repair_attempts: 0, used_fallback: false };
afterEach(cleanup);
test.each([undefined, '', '   '])('chapter header falls back to the current page number for %s', chapterTitle => {
  render(<MasterChrome config={config} band="header" values={{ pageNumber: 7, chapterTitle }} />);
  expect(screen.getByText('7')).toBeTruthy();
});
test('fixed chrome bands interpolate all slots outside the measured content grid with shared print tokens', () => {
  render(<PageCanvas result={result} tokens={tokens} chrome={{ config, chapterTitle: 'Results', totalPages: 9 }} />);
  expect(screen.getByText('Annual review')).toBeTruthy();
  expect(screen.getByText('Results')).toBeTruthy();
  expect(screen.getByText('Copyright 2026 Company')).toBeTruthy();
  expect(screen.getByText('Private')).toBeTruthy();
  expect(screen.getByText('Page 2 of 9')).toBeTruthy();
  const page = screen.getByTestId('page-canvas');
  expect(page.dataset.chromeHeader).toBe('true');
  expect(page.dataset.chromeFooter).toBe('true');
  expect(screen.getByTestId('page-content').contains(screen.getByText('Results'))).toBe(false);
  expect(page.style.getPropertyValue('--color-brand-primary')).toBe('#123456');
  expect(page.style.getPropertyValue('--chrome-band')).toBe('12mm');
});
test.each(['full_bleed_hero', 'section_divider'] as const)('%s suppresses chrome', archetype => {
  render(<PageCanvas result={result} layout={{ ...layout, archetype }} tokens={tokens} chrome={{ config }} />);
  expect(screen.queryByText('Annual review')).toBeNull();
});
test('cover and disabled mode suppress chrome and empty bands reserve no space', () => {
  const view = render(<PageCanvas result={result} tokens={tokens} chrome={{ config, isCover: true }} />);
  expect(screen.queryByText('Annual review')).toBeNull();
  view.rerender(<PageCanvas result={result} tokens={tokens} chrome={{ config: { ...config, enabled: false } }} />);
  expect(screen.queryByText('Annual review')).toBeNull();
  view.rerender(<PageCanvas result={result} tokens={tokens} chrome={{ config: { ...config, header_left: '', header_right: '' } }} />);
  expect(screen.getByTestId('page-canvas').dataset.chromeHeader).toBe('false');
  expect(screen.getByTestId('page-canvas').dataset.chromeFooter).toBe('true');
});
