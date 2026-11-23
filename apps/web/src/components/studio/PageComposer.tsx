'use client';
import { useState } from 'react';

export function PageComposer({ pageNumber, busy, onGenerate }: { pageNumber: number; busy: boolean; onGenerate: (text: string, files: File[]) => Promise<void> }) {
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  return <form className="page-composer studio-controls" onSubmit={event => { event.preventDefault(); void onGenerate(text, files); }}>
    <h2>Compose page {pageNumber}</h2>
    <label>Page text<textarea value={text} onChange={event => setText(event.target.value)} rows={7} disabled={busy} /></label>
    <label>Page images<input type="file" accept="image/*" multiple disabled={busy} onChange={event => setFiles(Array.from(event.target.files ?? []))} /></label>
    <button disabled={busy || (!text.trim() && !files.length)}>Generate options</button>
  </form>;
}
