import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { ComponentType } from 'react';
const modules = import.meta.glob('../../src/components/studio/Studio.tsx', { eager: true });
const Studio = (modules['../../src/components/studio/Studio.tsx'] as { Studio: ComponentType<{ sessionId?: string; debugWorkspace?: boolean }> } | undefined)?.Studio;
const canvas = vi.hoisted(() => ({ broken: false }));
vi.mock('../../src/engine/PageCanvas', () => ({ PageCanvas: () => { if (canvas.broken) throw new Error('Temporary browser rendering failure'); return <div>Canvas</div>; } }));
const context = { title: '', objective: '', tone_keywords: [], audience_mode: 'internal', page_size: 'A4', source_website_url: null };
const layout = { option_id: 'option_a', strategy_tag: 'clear', archetype: 'minimalist_swiss', rationale: 'Clear reading order', components: [] };
const pending = { page_id: 'p1', page_number: 1, input_blocks: [], input_assets: [], metrics_ledger: [], option_a: layout, option_b: { ...layout, option_id: 'option_b', rationale: 'Visual rhythm' } };
let state: Record<string, unknown>;
function mount(sessionId?: string, debugWorkspace = false) {
  expect(Studio, 'Studio must provide optional setup and persistent review').toBeDefined();
  if (!Studio) throw new Error('Missing Studio');
  return render(<Studio sessionId={sessionId} debugWorkspace={debugWorkspace} />);
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
beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (key: string) => saved.get(key) ?? null, setItem: (key: string, value: string) => saved.set(key, value) });
});
afterEach(() => { cleanup(); canvas.broken = false; vi.unstubAllGlobals(); vi.restoreAllMocks(); });
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
  expect(screen.getByRole('button', { name: 'Retry generation' }).hasAttribute('disabled')).toBe(false);
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

test('debug capability keeps normal authoring on the ordinary endpoint', async () => {
  mockApi(); state.debug_enabled = true; mount('s1');
  await screen.findByLabelText('Page text');
  expect(screen.getByRole('link', { name: 'Open debugger' }).getAttribute('href')).toBe('/sessions/s1/debug');
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'Ordinary source' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate options' }));
  await screen.findByRole('radio', { name: /Option A/ });
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/pages'))).toBe(true);
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/debug'))).toBe(false);
  expect(screen.queryByLabelText('Graph debugger')).toBeNull();
});

test('dedicated debug generation uses manual API and refresh restores its checkpoint', async () => {
  mockApi();
  state.debug_enabled = true;
  const debug = { session_id: 's1', checkpoint_id: 'cp', status: 'paused', next_nodes: ['profile'], last_node: null,
    state: { text: 'Manual source' }, node_input: {}, node_output: {}, interrupts: [], appearance: { tokens: {} } };
  const ordinaryFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/debug/pages')) { state.debug_active = true; return Response.json(debug); }
    if (String(url).endsWith('/debug')) return Response.json(state.debug_active ? debug : { ...debug, status: 'idle', next_nodes: [] });
    return ordinaryFetch(url, init);
  });
  const mounted = mount('s1', true);
  await screen.findByLabelText('Page text');
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'Manual source' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate options' }));
  await screen.findByRole('button', { name: 'Run profile' });
  expect(screen.queryByLabelText('Page text')).toBeNull();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/debug/pages'))).toBe(true);
  mounted.unmount();
  mount('s1', true);
  await screen.findByRole('button', { name: 'Run profile' });
});

test('normal Studio sends a paused manual page to its debugger without offering selection', async () => {
  mockApi(true); state.debug_enabled = true; state.debug_active = true; mount('s1');
  await screen.findByRole('link', { name: 'Open debugger' });
  expect(screen.queryByRole('radio')).toBeNull();
  expect(screen.queryByLabelText('Page text')).toBeNull();
  expect(screen.queryByLabelText('Graph debugger')).toBeNull();
});

test('debugger leaves an ordinary active page in Studio', async () => {
  mockApi(true); state.debug_enabled = true;
  state.active_page = { page_id: 'p1', page_number: 1, text: 'Ordinary', asset_ids: [] };
  const ordinaryFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/debug')) return Response.json({ session_id: 's1', status: 'idle', studio_active: true, appearance: { tokens: {} } });
    return ordinaryFetch(url, init);
  });
  mount('s1', true);
  await screen.findByText('This page is using Studio. Resume it in Studio before starting a manual run.');
  expect(screen.getByRole('link', { name: 'Open Studio' }).getAttribute('href')).toBe('/sessions/s1');
  expect(screen.queryByRole('radio')).toBeNull();
  expect(screen.queryByLabelText('Page text')).toBeNull();
});

test('a lost manual start restores its source and retries the same page identity', async () => {
  mockApi(); state.debug_enabled = true;
  const ordinaryFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/debug')) return Response.json({ session_id: 's1', status: 'idle', studio_active: false, appearance: { tokens: {} } });
    if (String(url).endsWith('/debug/pages')) throw new Error('Lost manual request');
    return ordinaryFetch(url, init);
  });
  const mounted = mount('s1', true);
  await screen.findByLabelText('Page text');
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'Saved manual source.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate options' }));
  await screen.findByRole('alert');
  const first = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/debug/pages'));
  const identity = JSON.parse(String(first?.[1]?.body)).page_id;
  mounted.unmount(); mount('s1', true);
  await screen.findByDisplayValue('Saved manual source.');
  fireEvent.click(screen.getByRole('button', { name: 'Retry generation' }));
  await screen.findByRole('alert');
  const calls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/debug/pages'));
  expect(calls).toHaveLength(2);
  expect(JSON.parse(String(calls[1][1]?.body)).page_id).toBe(identity);
  expect(identity).toBeTruthy();
});

test('stale debug submissions reload the current checkpoint and preserve the error', async () => {
  mockApi(); state.debug_enabled = true; state.debug_active = true;
  let checkpoint = 'first';
  const ordinaryFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/debug/step')) {
      checkpoint = 'current';
      return Response.json({ detail: 'Stale checkpoint; reload before stepping' }, { status: 409 });
    }
    if (String(url).endsWith('/debug')) return Response.json({ session_id: 's1', checkpoint_id: checkpoint, status: 'paused',
      next_nodes: [checkpoint === 'first' ? 'profile' : 'compliance_metrics_scan'], state: {}, interrupts: [], node_input: {}, node_output: {}, appearance: { tokens: {} } });
    return ordinaryFetch(url, init);
  });
  mount('s1', true);
  fireEvent.click(await screen.findByRole('button', { name: 'Run profile' }));
  await screen.findByRole('button', { name: 'Run compliance_metrics_scan' });
  expect(screen.getByRole('alert').textContent).toContain('Stale checkpoint');
});

test('refresh after failed upload generation reuses saved assets and revision replaces them', async () => {
  mockApi();
  const ordinaryFetch = vi.mocked(fetch).getMockImplementation()!;
  const saved = { page_id: 'durable', page_number: 1, text: 'Saved input.', asset_ids: ['uploaded'] };
  state.active_page = saved;
  let fail = true;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/assets')) return Response.json({ assets: [{ asset_id: 'replacement' }] });
    if (String(url).endsWith('/pages')) {
      const body = JSON.parse(String(init?.body));
      state.active_page = { ...saved, text: body.text, asset_ids: body.asset_ids };
      if (fail) return Response.json({ detail: 'Retry this page' }, { status: 503 });
    }
    return ordinaryFetch(url, init);
  });
  const mounted = mount('s1');
  await screen.findByDisplayValue('Saved input.');
  fireEvent.click(screen.getByRole('button', { name: 'Retry generation' }));
  await screen.findByRole('alert');
  const attempted = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/pages'));
  expect(JSON.parse(String(attempted?.[1]?.body))).toEqual({ page_id: 'durable', text: 'Saved input.', asset_ids: ['uploaded'], revise: false });
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/assets'))).toHaveLength(0);
  mounted.unmount(); mount('s1');
  await screen.findByDisplayValue('Saved input.');
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'Revised input.' } });
  fireEvent.change(screen.getByLabelText('Page images'), { target: { files: [new File(['image'], 'new.png', { type: 'image/png' })] } });
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Generate revised page' }));
  await screen.findByRole('radio', { name: /Option A/ });
  const calls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/pages'));
  expect(JSON.parse(String(calls.at(-1)?.[1]?.body))).toEqual({ page_id: 'durable', text: 'Revised input.', asset_ids: ['replacement'], revise: true });
});


test('saved review can render again after a browser failure without generation', async () => {
  mockApi(true);
  canvas.broken = true;
  const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
  mount('s1');
  await screen.findByRole('button', { name: 'Reopen saved review' });
  canvas.broken = false;
  fireEvent.click(screen.getByRole('button', { name: 'Reopen saved review' }));
  await screen.findByRole('radio', { name: /Option A/ });
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/pages'))).toBe(false);
  expect(logged).toHaveBeenCalled();
});

test('client saves identity and uploaded assets before a lost generation request', async () => {
  mockApi();
  const ordinaryFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/assets')) return Response.json({ assets: [{ asset_id: 'saved-upload' }] });
    if (String(url).endsWith('/pages')) throw new Error('Lost request');
    return ordinaryFetch(url, init);
  });
  const mounted = mount('s1');
  await screen.findByLabelText('Page text');
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'Original before network loss.' } });
  fireEvent.change(screen.getByLabelText('Page images'), { target: { files: [new File(['image'], 'photo.png', { type: 'image/png' })] } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate options' }));
  await screen.findByRole('alert');
  const first = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/pages'));
  const identity = JSON.parse(String(first?.[1]?.body)).page_id;
  expect(identity).toBeTruthy();
  mounted.unmount(); mount('s1');
  await screen.findByDisplayValue('Original before network loss.');
  fireEvent.click(screen.getByRole('button', { name: 'Retry generation' }));
  await screen.findByRole('alert');
  const calls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/pages'));
  expect(JSON.parse(String(calls.at(-1)?.[1]?.body))).toEqual({ page_id: identity, text: 'Original before network loss.', asset_ids: ['saved-upload'], revise: false });
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/assets'))).toHaveLength(1);
});

test.each(['auto', 'brand_led_editorial', 'consulting_report', 'campaign_presentation'])('setup sends the %s book direction', async direction => {
  mockApi(); mount();
  const select = screen.getByLabelText('Book direction');
  expect(Array.from((select as HTMLSelectElement).options).map(option => option.value)).toEqual(['auto', 'brand_led_editorial', 'consulting_report', 'campaign_presentation']);
  fireEvent.change(select, { target: { value: direction } });
  fireEvent.click(screen.getByRole('button', { name: 'Create book' }));
  await screen.findByLabelText('Page text');
  const call = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === 'POST');
  expect(JSON.parse(String(call?.[1]?.body)).context.direction).toBe(direction);
});

test('workspace puts the current action before contextual appearance and draft actions', async () => {
  mockApi(true); mount('s1');
  await screen.findByRole('radio', { name: /Option A/ });
  expect(screen.getByLabelText('Authoring progress').textContent).toContain('Review');
  expect(screen.getByText('Book appearance').closest('details')?.open).toBe(false);
  expect(screen.getByRole('radio', { name: /Option A/ }).getAttribute('tabindex')).toBe('0');
  expect(screen.getByRole('radio', { name: /Option B/ }).getAttribute('tabindex')).toBe('-1');
  fireEvent.keyDown(screen.getByRole('radio', { name: /Option A/ }), { key: 'ArrowRight' });
  expect(screen.getByRole('radio', { name: /Option B/ }).getAttribute('aria-checked')).toBe('true');
  expect(document.activeElement).toBe(screen.getByRole('radio', { name: /Option B/ }));
});

test('review shortcuts allow keyboard navigation links without committing a layout', async () => {
  mockApi(true); mount('s1');
  await screen.findByRole('radio', { name: /Option A/ });
  fireEvent.keyDown(screen.getByRole('link', { name: 'Reopen this book' }), { key: 'Enter' });
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/selection'))).toBe(false);
});
