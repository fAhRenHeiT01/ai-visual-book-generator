'use client';
import { useEffect, useState } from 'react';
import { PageCanvas } from '../../engine/PageCanvas';
import type { components } from '../../types/generated';
type S = components['schemas'];
type Choice = 'option_a' | 'option_b';
export function OptionComparison({ result, appearance, context, totalPages, busy, onConfirm }: { result: S['PageGenerationResult']; appearance: S['AppearanceResponse']; context: S['BookContext']; totalPages: number; busy: boolean; onConfirm: (choice: Choice) => void }) {
  const [choice, setChoice] = useState<Choice>('option_a');
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName) || event.target.isContentEditable)) return;
      if (busy || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === '1' || event.key === '2') { event.preventDefault(); setChoice(event.key === '1' ? 'option_a' : 'option_b'); }
      if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement)) { event.preventDefault(); onConfirm(choice); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [choice, busy, onConfirm]);
  return <section className="option-comparison studio-controls" aria-label="Review page options">
    <h2>Choose a layout for page {result.page_number}</h2><p>Press 1 or 2 to choose, then Enter to confirm.</p>
    <div className="options" role="radiogroup" aria-label="Layout options">
      {(['option_a', 'option_b'] as const).map((id, index) => <section className="option-card" key={id} data-archetype={result[id].archetype}>
        <button type="button" role="radio" aria-checked={choice === id} disabled={busy} onClick={() => setChoice(id)}>Option {index ? 'B' : 'A'}{choice === id ? ' · selected' : ''}</button>
        <p className="rationale">{result[id].rationale}</p>
        <div className="canvas-scroll"><PageCanvas result={result} layout={result[id]} tokens={appearance.tokens} pageSize={context.page_size} chrome={{ config: appearance.chrome, pageNumber: result.page_number, totalPages, chapterTitle: context.title, isCover: result.page_number === 1 }} /></div>
      </section>)}
    </div>
    <button type="button" disabled={busy} onClick={() => onConfirm(choice)}>Confirm selection</button>
  </section>;
}
