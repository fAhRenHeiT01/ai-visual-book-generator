'use client';
import { useEffect, useRef, useState } from 'react';
import type { components } from '../../types/generated';

type ActivePage = components['schemas']['ActivePage'];
export function PageComposer({ pageNumber, busy, activePage, onGenerate }: { pageNumber: number; busy: boolean; activePage?: ActivePage | null; onGenerate: (text: string, files: File[], revise: boolean, title?: string) => Promise<void> }) {
  const [text, setText] = useState(activePage?.text ?? '');
  const [title, setTitle] = useState(activePage?.title ?? '');
  const [files, setFiles] = useState<File[]>([]);
  const uploadInput = useRef<HTMLInputElement>(null);
  useEffect(() => { setFiles([]); if (uploadInput.current) uploadInput.current.value = ''; }, [activePage]);
  const revised = !!activePage && (text !== activePage.text || title !== (activePage.title ?? '') || files.length > 0);
  return <section className="compose-workspace studio-controls" aria-label="Compose a page"><form className="page-composer studio-controls" onSubmit={event => { event.preventDefault(); void onGenerate(text, files, revised, title.trim() || undefined); }}>
    <p className="eyebrow">02 / Page {pageNumber}</p><h2>Compose page {pageNumber}</h2><p className="field-help">Add your original copy and supporting images. We will create two layouts for you to compare.</p>{activePage && <p className="recovery-note">Your page input is saved. Retry generation or revise it below.</p>}
    <label>Page title (optional)<input value={title} onChange={event => setTitle(event.target.value)} disabled={busy} placeholder="Leave blank to infer from your copy" /></label>
    <label>Page text<textarea value={text} onChange={event => setText(event.target.value)} rows={7} disabled={busy} /></label>
    <label>Page images<input ref={uploadInput} type="file" accept="image/*" multiple disabled={busy} onChange={event => setFiles(Array.from(event.target.files ?? []))} /></label>
    {!!activePage?.asset_ids?.length && <p>{activePage.asset_ids?.length} saved image(s). Choose files to replace them.</p>}
    <button disabled={busy || (!text.trim() && !files.length && !activePage?.asset_ids?.length)}>{activePage ? revised ? 'Generate revised page' : 'Retry generation' : 'Generate options'}</button>
  </form><div className="preview-placeholder"><span aria-hidden="true">A / B</span><h2>Your next page starts here</h2><p>Generate options to compare two complete page previews.</p><p>Choose a layout to add it to your draft.</p></div></section>;
}
