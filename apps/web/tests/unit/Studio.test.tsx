import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ComponentType } from 'react';
const modules = import.meta.glob('../../src/components/studio/Studio.tsx', { eager: true });
const Studio = (modules['../../src/components/studio/Studio.tsx'] as { Studio: ComponentType<{ sessionId?: string }> } | undefined)?.Studio;
vi.mock('../../src/engine/PageCanvas', () => ({ PageCanvas: () => <div>Canvas</div> }));
const context = { title: '', objective: '', tone_keywords: [], audience_mode: 'internal', page_size: 'A4', source_website_url: null };
const layout = { option_id: 'option_a', strategy_tag: 'clear', archetype: 'minimalist_swiss', rationale: 'Clear reading order', components: [] };
const pending = { page_id: 'p1', page_number: 1, input_blocks: [], input_assets: [], metrics_ledger: [], option_a: layout, option_b: { ...layout, option_id: 'option_b', rationale: 'Visual rhythm' } };
let state: Record<string, unknown>;
function mount(sessionId?: string) {
  expect(Studio, 'Studio must provide optional setup and persistent review').toBeDefined();
  if (!Studio) throw new Error('Missing Studio');
  return render(<Studio sessionId={sessionId} />);
}
function mockApi(review = false) {
  state = { session_id: 's1', context, current_page_index: 1, assets: [], committed_pages: [], pending_review: review ? pending : null };
  return vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/appearance')) return Response.json({ status: 'unavailable', tokens: { theme_id: 'default', palette_source: 'preset' }, chrome: { enabled: false } });
    if (url.endsWith('/selection')) { state = { ...state, pending_review: null, committed_pages: [{ ...pending, selected_option_id: JSON.parse(String(init?.body)).option_id }], current_page_index: 2 }; return Response.json(pending); }
    if (url.endsWith('/pages')) { state.pending_review = pending; return Response.json(pending); }
    return Response.json(state);
  }));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
test('optional setup allows an empty book context and mounts phase two controls', async () => {
  mockApi(); mount();
  expect(screen.getByLabelText('Book title (optional)')).toBeTruthy();
  expect(screen.getByLabelText('Audience')).toBeTruthy();
  expect(screen.getByText(/Theme customization/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Create book' }));
  await screen.findByRole('button', { name: 'Generate options' });
  const call = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'POST');
  expect(JSON.parse(String(call?.[1]?.body)).context.title).toBe('');
});
test('refresh restores pending review with accessible options, keyboard selection and one confirmation', async () => {
  mockApi(true); mount('s1');
  await screen.findByRole('radio', { name: /Option A/ });
  expect(screen.getByText('Clear reading order')).toBeTruthy();
  expect(screen.getByText('Visual rhythm')).toBeTruthy();
  fireEvent.keyDown(window, { key: '2' });
  expect(screen.getByRole('radio', { name: /Option B/ }).getAttribute('aria-checked')).toBe('true');
  fireEvent.keyDown(window, { key: 'Enter' });
  fireEvent.keyDown(window, { key: 'Enter' });
  await screen.findByText('1 committed page');
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/selection'))).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Print draft' })).toBeTruthy();
});
test('generation pending and error states preserve input and allow retry', async () => {
  mockApi(); mount('s1');
  await screen.findByLabelText('Page text');
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'Exact original copy.' } });
  let fail!: (value: Response) => void;
  vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { fail = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Generate options' }));
  expect(screen.getByRole('status').textContent).toContain('Generating');
  fail(Response.json({ detail: 'Please retry' }, { status: 503 }));
  await screen.findByRole('alert');
  expect((screen.getByLabelText('Page text') as HTMLTextAreaElement).value).toBe('Exact original copy.');
  expect(screen.getByRole('button', { name: 'Generate options' }).hasAttribute('disabled')).toBe(false);
});
test('1 selects A while a layout control has focus, and editing text ignores shortcuts', async () => {
  mockApi(true); mount('s1');
  const optionB = await screen.findByRole('radio', { name: /Option B/ });
  fireEvent.click(optionB);
  fireEvent.keyDown(optionB, { key: '1' });
  expect(screen.getByRole('radio', { name: /Option A/ }).getAttribute('aria-checked')).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'Confirm selection' }));
  const text = await screen.findByLabelText('Page text');
  fireEvent.keyDown(text, { key: '2' });
  expect(screen.queryByRole('radio')).toBeNull();
});
