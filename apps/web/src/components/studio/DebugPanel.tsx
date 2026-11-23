'use client';
import { useState } from 'react';
import type { components } from '../../types/generated';
import { surfaceClasses } from '../../engine/blocks/SemanticBlock';

type S = components['schemas'];
const format = (value: unknown) => JSON.stringify(value, null, 2);
function Inspection({ title, value }: { title: string; value: unknown }) {
  return <details><summary>{title}</summary><pre style={{ whiteSpace: 'pre-wrap', maxHeight: '28rem', overflow: 'auto' }}>{format(value)}</pre></details>;
}

export function DebugPanel({ snapshot, busy, onStep, onReload }: {
  snapshot: S['DebugSnapshot']; busy: boolean; onStep: (response?: string) => void; onReload?: () => void;
}) {
  const [response, setResponse] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  const pending = snapshot.interrupts?.[0];
  const prompt = pending?.event === 'llm_request' ? pending.prompt : undefined;
  async function copyPrompt() {
    try { await navigator.clipboard.writeText(prompt ?? ''); setCopyStatus('Prompt copied.'); }
    catch { setCopyStatus('Select and copy the prompt from the field below.'); }
  }
  return <section className="studio-controls" aria-label="Graph debugger">
    <h2>DEBUG · manual graph</h2>
    <p>Inspect each node, then advance explicitly. LLM calls wait for your pasted response. No provider credentials are needed.</p>
    <p>Last completed node: <strong>{snapshot.last_node ?? 'None'}</strong>. Next: <strong>{snapshot.next_nodes?.join(', ') || snapshot.status}</strong>.</p>
    {onReload && <button type="button" disabled={busy} onClick={onReload}>Reload checkpoint</button>}
    {snapshot.status === 'paused' && !pending && <button type="button" disabled={busy} onClick={() => onStep()}>Run {snapshot.next_nodes?.join(', ')}</button>}
    {prompt && <>
      <h3>LLM prompt · {pending?.option_id}</h3>
      <p>Copy this prompt into a separate chat. It combines the system and strategy instructions, current page, layout history, and required response schema. Paste the chat's JSON reply below.</p>
      <button type="button" onClick={() => { void copyPrompt(); }}>Copy prompt</button>
      {copyStatus && <p role="status">{copyStatus}</p>}
      <label>Chat prompt<textarea aria-label="Chat prompt" readOnly rows={20} value={prompt} style={{ width: '100%' }} /></label>
      {!!pending?.images?.length && <div>
        <h3>Images to attach in the chat</h3>
        <p>Download these thumbnails and attach them alongside the prompt in the listed order.</p>
        {pending.images.map(image => {
          const url = `data:${image.mime_type};base64,${image.data}`;
          return <figure key={image.asset_id}>
            <img src={url} alt={`${image.asset_id} thumbnail for chat`} style={{ maxWidth: '16rem', maxHeight: '12rem', objectFit: 'contain' }} />
            <figcaption><a href={url} download={`${image.asset_id}.png`}>Download {image.asset_id} thumbnail</a></figcaption>
          </figure>;
        })}
      </div>}
      <label>Manual LLM response<textarea aria-label="Manual LLM response" rows={12} value={response} onChange={event => setResponse(event.target.value)} disabled={busy} style={{ width: '100%' }} /></label>
      <p>Paste the response as returned. Malformed or invalid layouts enter the normal validation, repair, and bounded fallback flow.</p>
      <button type="button" disabled={busy || !response.trim()} onClick={() => onStep(response)}>Submit response</button>
    </>}
    {pending?.event === 'review' && <p>Review the rendered options below and confirm a selection. The commit node requires a separate step afterward.</p>}
    {snapshot.status === 'completed' && <p>Page committed. The final node output is available below.</p>}
    <Inspection title="Node input" value={snapshot.node_input} />
    <Inspection title="Node output" value={snapshot.node_output} />
    <Inspection title="Current graph state" value={snapshot.state} />
    <details><summary>Theme tokens and semantic placeholders</summary>
      <p>LLM layouts use semantic surface roles. The renderer resolves them to CSS variables using these theme values.</p>
      <table><thead><tr><th>Token</th><th>CSS variable</th><th>Value</th></tr></thead><tbody>
        {Object.entries(snapshot.appearance.tokens).filter(([key]) => key.startsWith('color_')).map(([key, value]) => <tr key={key}>
          <td>{key}</td><td>{`--${key.replaceAll('_', '-')}`}</td><td><span aria-hidden="true" style={{ display: 'inline-block', width: '1em', height: '1em', backgroundColor: String(value) }} /> {String(value)}</td>
        </tr>)}
      </tbody></table>
      <Inspection title="Renderer surface classes" value={surfaceClasses} />
      <Inspection title="Appearance and chrome placeholders" value={snapshot.appearance} />
    </details>
  </section>;
}
