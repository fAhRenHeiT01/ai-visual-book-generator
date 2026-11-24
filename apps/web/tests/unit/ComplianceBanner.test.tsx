import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { ComplianceBanner } from '../../src/components/compliance/ComplianceBanner';
import { ExportAction } from '../../src/components/draft/ExportAction';
import { sessionApi } from '../../src/lib/sessionApi';
import type { components } from '../../src/types/generated';
type S = components['schemas'];
vi.mock('../../src/lib/sessionApi', () => ({ sessionApi: { compliance: vi.fn(), decide: vi.fn(), browserPage: (_id: string, page: unknown) => page } }));
vi.mock('../../src/engine/PageCanvas', () => ({ PageCanvas: ({ result }: { result: S['PageGenerationResult'] }) => <div>{result.input_blocks[0]?.text}</div> }));
const report: S['ComplianceReport'] = { status: 'available', audience_mode: 'client_facing', eligible: false, ledger: [{ page_id: 'p1', decision: null, metric: { metric_id: 'm1', source_block_id: 'b1', raw_value: '$4.2M ARR', context_snippet: '[INTERNAL] $4.2M ARR', classification: 'internal', approved_for_export: false } }], publishable_pages: [] };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); });
test('current-page review groups repeated metrics into one exact statement and clears on navigation', async () => {
  const snippet = '😀 [INTERNAL] 42% YoY versus 42% YoY';
  const ledger = [
    { page_id: 'p1', source_start: 13, source_end: 20, decision: 'approve' as const, metric: { ...report.ledger![0].metric, metric_id: 'first', raw_value: '42% YoY', context_snippet: snippet } },
    { page_id: 'p1', source_start: 28, source_end: 35, decision: 'redact' as const, metric: { ...report.ledger![0].metric, metric_id: 'second', raw_value: '42% YoY', context_snippet: snippet } },
    { ...report.ledger![0], page_id: 'p2', metric: { ...report.ledger![0].metric, context_snippet: 'Other page $4.2M ARR' } },
  ];
  vi.mocked(sessionApi.compliance).mockResolvedValue({ ...report, ledger });
  const view = render(<ComplianceBanner sessionId="s1" pageId="p1" />);
  const statement = await screen.findByTestId('compliance-statement');
  expect(statement.textContent).toBe(snippet);
  expect(screen.getAllByTestId('compliance-statement')).toHaveLength(1);
  expect(Array.from(statement.querySelectorAll('[data-metric-id]')).map(el => [el.textContent, el.getAttribute('data-decision')])).toEqual([
    ['42% YoY', 'approve'], ['42% YoY', 'redact'],
  ]);
  expect(screen.queryByText('Other page $4.2M ARR')).toBeNull();
  view.rerender(<ComplianceBanner sessionId="s1" pageId="p2" />);
  expect(screen.queryByText((_, el) => el?.getAttribute('data-testid') === 'compliance-statement' && el.textContent === snippet)).toBeNull();
  expect((await screen.findByTestId('compliance-statement')).textContent).toBe('Other page $4.2M ARR');
  view.rerender(<ComplianceBanner sessionId="s1" pageId="empty" />);
  expect(screen.queryByTestId('compliance-statement')).toBeNull();
});
test.each(['approve', 'redact'] as const)('%s all persists every current-page occurrence only', async action => {
  const ledger = [report.ledger![0], { ...report.ledger![0], metric: { ...report.ledger![0].metric, metric_id: 'm2' } },
    { ...report.ledger![0], page_id: 'p2' }];
  vi.mocked(sessionApi.compliance).mockResolvedValue({ ...report, ledger });
  vi.mocked(sessionApi.decide).mockImplementation(async (_id, decision) => ({ ...report, ledger: ledger.map(item =>
    item.page_id === decision.page_id && item.metric.metric_id === decision.metric_id ? { ...item, decision: action } : item) }));
  const onDecision = vi.fn(async () => {});
  render(<ComplianceBanner sessionId="s1" pageId="p1" onDecision={onDecision} />);
  fireEvent.click(await screen.findByRole('button', { name: action === 'approve' ? 'Approve all' : 'Redact all' }));
  await waitFor(() => expect(sessionApi.decide).toHaveBeenCalledTimes(2));
  expect(vi.mocked(sessionApi.decide).mock.calls.map(([, decision]) => decision)).toEqual([
    { page_id: 'p1', metric_id: 'm1', action }, { page_id: 'p1', metric_id: 'm2', action },
  ]);
  await waitFor(() => expect(onDecision).toHaveBeenCalledOnce());
});
test('review shows audience, exact flagged source, locked and approved states', async () => {
  vi.mocked(sessionApi.compliance).mockResolvedValue(report);
  vi.mocked(sessionApi.decide).mockResolvedValue({ ...report, eligible: true, ledger: [{ ...report.ledger![0], decision: 'approve' }] });
  const onDecision = vi.fn(async () => {});
  render(<ComplianceBanner sessionId="s1" pageId="p1" onDecision={onDecision} />);
  await screen.findByText('[INTERNAL] $4.2M ARR');
  expect(screen.getByText(/client_facing/)).toBeTruthy();
  expect(screen.getByText(/Export locked/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
  await screen.findByText(/Export ready/);
  expect(sessionApi.decide).toHaveBeenCalledWith('s1', { page_id: 'p1', metric_id: 'm1', action: 'approve' });
  expect(onDecision).toHaveBeenCalledOnce();
});
test('redacted state survives remount and decision failures keep review locked', async () => {
  vi.mocked(sessionApi.compliance).mockResolvedValue({ ...report, eligible: true, ledger: [{ ...report.ledger![0], decision: 'redact' }] });
  const mounted = render(<ComplianceBanner sessionId="s1" pageId="p1" />);
  await screen.findByText('redact');
  mounted.unmount();
  vi.mocked(sessionApi.compliance).mockResolvedValue(report);
  vi.mocked(sessionApi.decide).mockRejectedValue(new Error('Review changed'));
  render(<ComplianceBanner sessionId="s1" pageId="p1" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Redact' }));
  await screen.findByRole('alert');
  expect(screen.getByText(/Export locked/)).toBeTruthy();
});
test('print rechecks authoritative eligibility and renders server redacted copy', async () => {
  const print = vi.spyOn(window, 'print').mockImplementation(() => {});
  const layout: S['PageLayoutAST'] = { option_id: 'option_a', archetype: 'minimalist_swiss', strategy_tag: 'clear', rationale: 'Source placement', components: [], surface_role: 'paper', density_scale: 'normal', column_count: 1 };
  const page: S['PageGenerationResult'] = { page_id: 'p1', page_number: 1, title: null, input_blocks: [{ block_id: 'b1', text: '[INTERNAL] [REDACTED]', kind: 'paragraph', word_count: 2, char_count: 21 }], input_assets: [], metrics_ledger: [], option_a: layout, option_b: { ...layout, option_id: 'option_b' }, selected_option_id: 'option_a', repair_attempts: 0, used_fallback: false };
  vi.mocked(sessionApi.compliance).mockResolvedValue({ ...report, eligible: true, publishable_pages: [page] });
  render(<ExportAction sessionId="s1" disabled={false} pages={[page]} context={{ audience_mode: 'client_facing', title: '', objective: '', page_size: 'A4', source_website_url: null }} appearance={{ tokens: {}, chrome: {} } as S['AppearanceResponse']} />);
  const button = screen.getByRole('button', { name: 'Print draft' });
  await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(print).toHaveBeenCalledOnce());
  expect(screen.getByText('[INTERNAL] [REDACTED]')).toBeTruthy();
  expect(sessionApi.compliance).toHaveBeenCalledTimes(2);
});
test('print stays locked when unavailable and a changed server decision refuses printing', async () => {
  const print = vi.spyOn(window, 'print').mockImplementation(() => {});
  vi.mocked(sessionApi.compliance).mockResolvedValueOnce({ ...report, eligible: true }).mockResolvedValueOnce(report);
  render(<ExportAction sessionId="s1" disabled={false} pages={[]} context={{ audience_mode: 'client_facing', title: '', objective: '', page_size: 'A4', source_website_url: null }} appearance={{ tokens: {}, chrome: {} } as S['AppearanceResponse']} />);
  const button = screen.getByRole('button', { name: 'Print draft' });
  await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
  fireEvent.click(button);
  await screen.findByRole('alert');
  expect(print).not.toHaveBeenCalled();
  expect(button.hasAttribute('disabled')).toBe(true);
});
