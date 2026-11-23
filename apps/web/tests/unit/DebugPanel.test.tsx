import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ComponentType } from 'react';
const modules = import.meta.glob('../../src/components/studio/DebugPanel.tsx', { eager: true });
const Panel = (modules['../../src/components/studio/DebugPanel.tsx'] as { DebugPanel: ComponentType<any> } | undefined)?.DebugPanel;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test('manual LLM response stays intact and request, node states and theme are inspectable', async () => {
  expect(Panel, 'DebugPanel must expose the manual graph controls').toBeDefined();
  if (!Panel) return;
  const advance = vi.fn();
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  const prompt = 'Actual system instructions\n\nExact source: café {theme}\n\nResponse JSON schema';
  render(<Panel snapshot={{ status: 'paused', checkpoint_id: 'cp', next_nodes: ['generate_candidates'], last_node: 'compliance_metrics_scan',
    state: { text: 'Original' }, node_input: { text: 'Original' }, node_output: { metrics_ledger: [] },
    appearance: { tokens: { color_brand_primary: '#123456' } },
    interrupts: [{ event: 'llm_request', option_id: 'option_a', prompt, images: [], request: { system_instruction: 'SDK-only envelope', contents: [] } }] }}
    busy={false} onStep={advance} />);
  expect((screen.getByLabelText('Chat prompt') as HTMLTextAreaElement).value).toBe(prompt);
  expect(screen.queryByLabelText('LLM API request')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Copy prompt' }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(prompt));
  expect(screen.getByText(/Node input/)).toBeTruthy();
  expect(screen.getByText(/Node output/)).toBeTruthy();
  expect(screen.getByText(/Theme tokens/)).toBeTruthy();
  const raw = '{"unknown":"test the validator"}';
  fireEvent.change(screen.getByLabelText('Manual LLM response'), { target: { value: raw } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }));
  expect(advance).toHaveBeenCalledWith(raw);
});

test('metadata prompts expose no image attachments or downloads even for a stale browser snapshot', () => {
  expect(Panel).toBeDefined();
  if (!Panel) return;
  render(<Panel snapshot={{ status: 'paused', next_nodes: ['generate_candidates'], state: {}, node_input: {}, node_output: {}, appearance: { tokens: {} },
    interrupts: [{ event: 'llm_request', option_id: 'option_a', prompt: 'Asset img_01: chart, 2000 by 1200.',
      images: [{ asset_id: 'img_01', mime_type: 'image/png', data: 'bounded-thumbnail-data' }] }] }} busy={false} onStep={vi.fn()} />);
  expect(screen.queryByRole('link')).toBeNull();
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.queryByText(/Images to attach/)).toBeNull();
  expect((screen.getByLabelText('Chat prompt') as HTMLTextAreaElement).value).toContain('2000 by 1200');
});

test('commit requires a separate advance and busy controls prevent duplicate steps', () => {
  expect(Panel).toBeDefined();
  if (!Panel) return;
  render(<Panel snapshot={{ status: 'paused', next_nodes: ['commit_page'], last_node: 'human_review_interrupt', state: {}, node_input: {}, node_output: {}, interrupts: [], appearance: { tokens: {} } }} busy onStep={vi.fn()} />);
  expect(screen.getByRole('button', { name: 'Run commit_page' }).hasAttribute('disabled')).toBe(true);
});
