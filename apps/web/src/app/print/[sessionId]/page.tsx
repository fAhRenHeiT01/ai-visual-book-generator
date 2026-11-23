'use client';

import { useEffect, useState, type CSSProperties } from 'react';
import { useParams } from 'next/navigation';
import type { components } from '../../../types/generated';
import { apiOrigin } from '../../../config/env';
import { PageCanvas } from '../../../engine/PageCanvas';
import { sessionApi } from '../../../lib/sessionApi';

type Manifest = components['schemas']['PrintManifest'];

export default function PrintBook() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState('');
  const [range, setRange] = useState({ start: 0, end: Infinity, compact: false });
  useEffect(() => {
    let active = true;
    delete document.documentElement.dataset.printReady;
    const params = new URLSearchParams(window.location.search);
    setRange({ start: Number(params.get('start') ?? 0), end: Number(params.get('end') ?? Infinity), compact: params.get('compact') === '1' });
    fetch(`${apiOrigin}/api/v1/sessions/${encodeURIComponent(sessionId)}/print-data`, { cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('Complete compliance review before exporting.');
        return response.json() as Promise<Manifest>;
      }).then(data => { if (active) setManifest(data); })
      .catch(reason => { if (active) setError(String(reason)); });
    return () => { active = false; delete document.documentElement.dataset.printReady; };
  }, [sessionId]);
  useEffect(() => {
    if (!manifest) return;
    let active = true;
    const ready = async () => {
      await document.fonts.ready;
      await Promise.all(Array.from(document.querySelectorAll<HTMLImageElement>('.print-book img')).map(async image => {
        image.loading = 'eager';
        await image.decode();
      }));
      // PageCanvas settles after its own font and image measurement pass.
      const settled = () => {
        if (!active) return;
        const canvases = Array.from(document.querySelectorAll<HTMLElement>('.print-book .page-canvas'));
        if (canvases.length && canvases.every(canvas => canvas.dataset.settled === 'true')) {
          requestAnimationFrame(() => requestAnimationFrame(() => { if (active) document.documentElement.dataset.printReady = 'true'; }));
        } else requestAnimationFrame(settled);
      };
      settled();
    };
    void ready().catch(() => { if (active) setError('A print asset could not be decoded.'); });
    return () => { active = false; };
  }, [manifest]);
  if (error) return <p role="alert">{error}</p>;
  if (!manifest) return <p>Preparing book…</p>;
  const styles = { '--export-safety': `${manifest.safety_buffer_percent}%` } as CSSProperties;
  return <main className={`print-book${range.compact ? ' print-compact' : ''}`} style={styles}>
    <style>{`@page { size: ${manifest.context.page_size === 'A4' ? 'A4' : 'letter'}; margin: 0; }`}</style>
    {manifest.pages.slice(range.start, range.end).map(item => {
      const result = sessionApi.browserPage(sessionId, item.result, 'print');
      const selected = result.selected_option_id === result.option_b.option_id ? result.option_b : result.option_a;
      return <section className="print-page" id={item.anchor} data-page-number={item.page_number} data-kind={item.kind} key={item.anchor}>
        <PageCanvas result={result} tokens={manifest.tokens} pageSize={manifest.context.page_size}
          layout={range.compact ? { ...selected, density_scale: 'compact' } : selected}
          chrome={{ config: manifest.chrome, pageNumber: item.page_number, totalPages: item.total_pages,
            chapterTitle: item.chapter_title, isCover: item.kind === 'cover' || item.kind === 'closing_cover' }} />
        {item.kind === 'toc' && <nav className="print-toc" aria-label="Contents">{manifest.toc.map((entry, index) =>
          <a key={`${entry.anchor}-${index}`} href={`#${entry.anchor}`} data-destination={entry.page_number}><span>{entry.title}</span><span>{entry.page_number}</span></a>)}</nav>}
      </section>;
    })}
  </main>;
}
