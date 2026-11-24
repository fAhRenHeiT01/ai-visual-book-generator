import { PagePreview } from '../studio/PagePreview';
import { PageCanvas } from '../../engine/PageCanvas';
import type { components } from '../../types/generated';
import { ExportAction } from './ExportAction';
import { pageChapterTitles } from '../../engine/MasterChrome';
type S = components['schemas'];
export function DraftViewer({ sessionId, pages, context, appearance }: { sessionId: string; pages: S['PageGenerationResult'][]; context: S['BookContext']; appearance: S['AppearanceResponse'] }) {
  const chapters = pageChapterTitles(pages);
  return <section id="draft" className="draft-viewer" aria-label="Committed draft">
    <div className="studio-controls section-heading"><p className="eyebrow">03 / Saved pages</p><h2>Draft</h2><p>{pages.length} committed page{pages.length === 1 ? '' : 's'}</p></div>
    {!pages.length && <p className="studio-controls empty-state">Your draft is empty. Generate a page and confirm a layout to start building your book.</p>}
    {!!pages.length && <nav className="draft-navigation studio-controls" aria-label="Draft pages">{pages.map(page => <a key={page.page_id} href={`#draft-page-${page.page_number}`}>Page {page.page_number}</a>)}</nav>}
    <ExportAction disabled={!pages.length} sessionId={sessionId} pages={pages} context={context} appearance={appearance} />
    <div className="draft-pages">{pages.map((page, index) => <div className="draft-page" id={`draft-page-${page.page_number}`} key={page.page_id}><p className="studio-controls draft-caption">Page {page.page_number} · Saved layout</p><PagePreview><PageCanvas result={page} tokens={appearance.tokens} pageSize={context.page_size} chrome={{ config: appearance.chrome, pageNumber: page.page_number, totalPages: pages.length, chapterTitle: chapters[index] }} /></PagePreview></div>)}</div>
  </section>;
}
