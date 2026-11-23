'use client';
import { useEffect, useRef, useState } from 'react';
import type { components } from '../../types/generated';

type ActivePage = components['schemas']['ActivePage'];
export function PageComposer({ pageNumber, busy, activePage, onGenerate }: { pageNumber: number; busy: boolean; activePage?: ActivePage | null; onGenerate: (text: string, files: File[], revise: boolean) => Promise<void> }) {
  const [text, setText] = useState(activePage?.text ?? '');
  const [files, setFiles] = useState<File[]>([]);
  const uploadInput = useRef<HTMLInputElement>(null);
  useEffect(() => { setFiles([]); if (uploadInput.current) uploadInput.current.value = ''; }, [activePage]);
  const revised = !!activePage && (text !== activePage.text || files.length > 0);
  return <form className="page-composer studio-controls" onSubmit={event => { event.preventDefault(); void onGenerate(text, files, revised); }}>
    <h2>Compose page {pageNumber}</h2>
    <label>Page text<textarea value={text} onChange={event => setText(event.target.value)} rows={7} disabled={busy} /></label>
    <label>Page images<input ref={uploadInput} type="file" accept="image/*" multiple disabled={busy} onChange={event => setFiles(Array.from(event.target.files ?? []))} /></label>
    {!!activePage?.asset_ids?.length && <p>{activePage.asset_ids?.length} saved image(s). Choose files to replace them.</p>}
    <button disabled={busy || (!text.trim() && !files.length && !activePage?.asset_ids?.length)}>{activePage ? revised ? 'Generate revised page' : 'Retry generation' : 'Generate options'}</button>
  </form>;
}
