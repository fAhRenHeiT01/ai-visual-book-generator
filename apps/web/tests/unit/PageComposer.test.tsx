import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { PageComposer } from '../../src/components/studio/PageComposer';

afterEach(cleanup);
test('optional page title is sent separately from unchanged pasted body copy', () => {
  const generate = vi.fn(async () => {});
  render(<PageComposer pageNumber={1} busy={false} onGenerate={generate} />);
  fireEvent.change(screen.getByLabelText('Page title (optional)'), { target: { value: 'Explicit chapter' } });
  fireEvent.change(screen.getByLabelText('Page text'), { target: { value: 'First\nsecond\tcopy.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate options' }));
  expect(generate).toHaveBeenCalledWith('First\nsecond\tcopy.', [], false, 'Explicit chapter');
});
test('a saved title restores and editing only it creates a revision', () => {
  const generate = vi.fn(async () => {});
  render(<PageComposer pageNumber={2} busy={false} activePage={{ page_id: 'saved', page_number: 2, text: 'Exact copy.', title: 'Saved chapter', asset_ids: [] }} onGenerate={generate} />);
  expect(screen.getByDisplayValue('Saved chapter')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Page title (optional)'), { target: { value: 'Revised chapter' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate revised page' }));
  expect(generate).toHaveBeenCalledWith('Exact copy.', [], true, 'Revised chapter');
});
