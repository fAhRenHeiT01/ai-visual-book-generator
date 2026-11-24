'use client';
import { useEffect, useState } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';

type S = components['schemas'];
export function Examples({ busy, onOpen }: { busy: boolean; onOpen: (id: string) => void }) {
  const [examples, setExamples] = useState<S['ExampleSummary'][]>([]);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!expanded) return;
    let active = true;
    sessionApi.examples().then(catalog => { if (active) { setExamples(catalog.examples); setError(''); } })
      .catch((cause: Error) => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, [attempt, expanded]);
  return <details className="examples studio-controls" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary>Examples · Explore 25 sample pages</summary>
    <h2>Start with an example</h2>
    <p>Scripted fixture runs with fictional copy and local images. Each opening creates an independent book, ready to review, edit and export. No provider key is needed.</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>Reload examples</button></p>}
    <ul className="example-grid">{examples.map(example => <li key={example.id}>
      <button type="button" disabled={busy} onClick={() => { setExpanded(false); onOpen(example.id); }}>{example.title}</button>
      <p>{example.outcome === 'normal' ? 'Ready for review' : example.outcome === 'repair' ? 'Demonstrates automatic repair' : example.outcome === 'fallback' ? 'Demonstrates safe fallback' : 'Publication approval required'}</p>
      <small>{example.coverage_tags.join(' · ')}</small>
    </li>)}</ul>
  </details>;
}
