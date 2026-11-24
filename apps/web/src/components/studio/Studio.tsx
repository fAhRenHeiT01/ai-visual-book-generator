'use client';
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { BookSetup } from '../setup/BookSetup';
import { Examples } from '../setup/Examples';
import { ThemeControls } from '../setup/ThemeControls';
import { ComplianceBanner } from '../compliance/ComplianceBanner';
import { DraftViewer } from '../draft/DraftViewer';
import { PageComposer } from './PageComposer';
import { OptionComparison } from './OptionComparison';
import { DebugPanel } from './DebugPanel';
type S = components['schemas'];
function GenerationProgress() {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const modal = dialog.current;
    if (modal && !modal.open) {
      if (modal.showModal) modal.showModal();
      else modal.open = true;
    }
  }, []);
  return <dialog ref={dialog} className="generation-progress studio-controls" aria-modal="true" aria-labelledby="generation-progress-title" onCancel={event => event.preventDefault()}>
    <span className="generation-spinner" aria-hidden="true" />
    <p id="generation-progress-title" role="status">Generating options</p>
  </dialog>;
}
class ReviewBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div className="studio-controls" role="alert">The saved review could not be displayed. <button onClick={() => this.setState({ failed: false })}>Reopen saved review</button></div>;
    return this.props.children;
  }
}
function SavedBooks({ busy }: { busy: boolean }) {
  const [books, setBooks] = useState<S['SessionSummary'][]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [confirmation, setConfirmation] = useState<string>();
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    sessionApi.list().then(result => { if (active) setBooks(result.sessions); })
      .catch((cause: Error) => { if (active) setError(cause.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);
  async function remove(id: string) {
    if (deleting) return;
    setDeleting(true); setError('');
    try {
      await sessionApi.remove(id);
      setBooks(current => current.filter(book => book.session_id !== id)); setConfirmation(undefined);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Please retry deleting this book.'); }
    finally { setDeleting(false); }
  }
  return <section className="studio-controls" aria-labelledby="saved-books-title">
    <h2 id="saved-books-title">Saved books</h2>
    {loading && <p role="status">Loading saved books…</p>}
    {error && <p role="alert"><span>{error}</span> <button type="button" disabled={deleting || busy} onClick={() => setAttempt(value => value + 1)}>Reload saved books</button></p>}
    {!loading && !error && !books.length && <p>No saved books yet. Create a book or open an example to get started.</p>}
    <ul>{books.map(book => <li key={book.session_id}>
      <h3>{book.title}</h3>
      <p>{book.committed_page_count} committed {book.committed_page_count === 1 ? 'page' : 'pages'} · Next page {book.current_page_index}</p>
      <p>Saved automatically · <a href={`/sessions/${encodeURIComponent(book.session_id)}`} aria-label={`Reopen this book: ${book.title}`}>Reopen this book</a></p>
      {confirmation === book.session_id ? <div role="dialog" aria-labelledby={`delete-${book.session_id}`} onKeyDown={event => { if (event.key === 'Escape' && !deleting) setConfirmation(undefined); }}>
        <h4 id={`delete-${book.session_id}`}>Delete {book.title}?</h4>
        <p>This permanently deletes this book, its pages and uploaded assets.</p>
        <button type="button" autoFocus disabled={deleting} onClick={() => setConfirmation(undefined)}>Cancel</button>
        <button type="button" disabled={deleting || busy} onClick={() => { void remove(book.session_id); }}>{deleting ? 'Deleting book…' : 'Permanently delete book'}</button>
      </div> : <button type="button" disabled={deleting || busy} aria-label={`Delete ${book.title}`} onClick={() => setConfirmation(book.session_id)}>Delete</button>}
    </li>)}</ul>
  </section>;
}
export function Studio({ sessionId, debugWorkspace = false }: { sessionId?: string; debugWorkspace?: boolean }) {
  const [session, setSession] = useState<S['SessionSnapshot']>();
  const [appearance, setAppearance] = useState<S['AppearanceResponse']>();
  const [debug, setDebug] = useState<S['DebugSnapshot']>();
  const [status, setStatus] = useState(sessionId ? 'Loading book…' : '');
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [reviewPage, setReviewPage] = useState<{ scope: string; pageId: string }>();
  const [compliance, setCompliance] = useState<S['ComplianceReport']>();
  const locked = useRef(false);
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    Promise.all([sessionApi.load(sessionId), sessionApi.appearance(sessionId)]).then(async ([snapshot, theme]) => {
      const checkpoint = debugWorkspace && snapshot.debug_enabled ? await sessionApi.debug(sessionId) : undefined;
      if (active) { setSession(snapshot); setAppearance(theme); setDebug(checkpoint); setStatus(''); setError(''); }
    }).catch((cause: Error) => { if (active) { setError(cause.message); setStatus(''); } });
    return () => { active = false; };
  }, [sessionId, retry, debugWorkspace]);
  const refresh = useCallback(async () => {
    if (session) {
      const snapshot = await sessionApi.load(session.session_id);
      const checkpoint = debugWorkspace && snapshot.debug_enabled ? await sessionApi.debug(session.session_id) : undefined;
      setSession(snapshot); setDebug(checkpoint);
    }
  }, [session, debugWorkspace]);
  const pendingId = session?.pending_review?.page_id;
  useEffect(() => {
    if (session && pendingId) return sessionApi.review(session.session_id, pendingId, () => { void refresh().catch((cause: Error) => setError(cause.message)); });
  }, [session?.session_id, pendingId, refresh]);
  async function run(message: string, action: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setStatus(message); setError('');
    try { await action(); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Please retry.'); }
    finally { locked.current = false; setStatus(''); }
  }
  function debugStep(response?: string) {
    if (!session || !debug?.checkpoint_id) return;
    void run('Advancing graph…', async () => {
      try {
        const checkpoint = await sessionApi.debugStep(session.session_id, debug.checkpoint_id!, response);
        setDebug(checkpoint);
        setSession(await sessionApi.load(session.session_id));
      } catch (cause) {
        await refresh();
        throw cause;
      }
    });
  }
  const debugging = debugWorkspace && debug?.status === 'paused';
  const debugReview = debugging && debug.interrupts?.[0]?.event === 'review' && !!session?.pending_review && session.pending_review.page_id === debug.state?.page_id;
  const otherWorkflow = session && (debugWorkspace ? !session.debug_enabled || debug?.studio_active : session.debug_active);
  const action = !session ? 'Setup' : session.pending_review ? 'Review' : 'Compose';
  const currentPageId = session?.pending_review?.page_id ?? session?.active_page?.page_id;
  const reviewScope = `${session?.session_id}:${currentPageId ?? session?.current_page_index}`;
  const activeReviewId = reviewPage?.scope === reviewScope ? reviewPage.pageId : currentPageId;
  const selectReviewPage = (pageId: string) => setReviewPage({ scope: reviewScope, pageId });
  return <main className="studio">
    <header className="studio-controls studio-header"><a href="/">Visual Book Generator</a><h1>{session?.context.title || 'Visual Book Generator'}</h1>{session && (debugWorkspace || session.debug_enabled) && <p>{debugWorkspace && <a href={`/sessions/${session.session_id}`}>Open Studio</a>}{session.debug_enabled && !debugWorkspace && <a href={`/sessions/${session.session_id}/debug`}>Open debugger</a>}</p>}</header>
    <nav className="authoring-progress studio-controls" aria-label="Authoring progress"><ol>{['Setup', 'Compose', 'Review'].map(step => <li key={step} aria-current={step === action ? 'step' : undefined}>{step}</li>)}</ol>{session && <a href="#draft">View draft · {session.committed_pages?.length ?? 0} pages</a>}</nav>
    {status === 'Generating options…' ? <GenerationProgress /> : status && <p className="studio-controls" role="status">{status}</p>}
    {error && <div className="studio-controls" role="alert">{error}{sessionId && !session && <button onClick={() => { setStatus('Loading book…'); setRetry(value => value + 1); }}>Retry loading book</button>}</div>}
    {!session && !sessionId && !debugWorkspace && <SavedBooks busy={!!status} />}
    {!session && !sessionId && !debugWorkspace && <Examples busy={!!status} onOpen={id => { void run('Opening example…', async () => {
      const created = await sessionApi.openExample(id);
      const theme = await sessionApi.appearance(created.session_id);
      setSession(created); setAppearance(theme); setDebug(undefined);
      window.history.pushState(null, '', `/sessions/${created.session_id}`);
    }); }} />}
    {session?.example_id && <p className="example-notice studio-controls">Scripted fixture run · {session.example_id} · This book has its own review and source assets.</p>}
    {!session && !sessionId && <div className="studio-controls"><BookSetup busy={!!status} onCreate={context => { void run('Creating book…', async () => {
      const created = await sessionApi.create(context);
      const theme = await sessionApi.appearance(created.session_id);
      setSession(created); setAppearance(theme); window.history.pushState(null, '', `/sessions/${created.session_id}`);
    }); }} /></div>}
    {session && appearance && <>
      <details className="appearance-disclosure studio-controls"><summary>Book appearance</summary><ThemeControls sessionId={session?.session_id} appearance={appearance} onAppearanceChange={setAppearance} locked={!!session?.active_page || !!session?.debug_active || !!session?.pending_review || !!session?.committed_pages?.length || status === 'Generating options…'} /></details>
      {otherWorkflow && <p className="studio-controls">{debugWorkspace ? session.debug_enabled ? 'This page is using Studio. Resume it in Studio before starting a manual run.' : 'The debugger is unavailable on this server. Continue in Studio.' : 'This page is paused in the debugger. Open the debugger to resume and review it.'}</p>}
      {debugWorkspace && session.debug_enabled && debug && !otherWorkflow && <DebugPanel key={debug.checkpoint_id} snapshot={{ ...debug, appearance }} busy={!!status} onStep={debugStep} onReload={() => { void run('Reloading checkpoint…', refresh); }} />}
      {otherWorkflow || (debugging && !debugReview) ? null : session.pending_review ? <ReviewBoundary key={session.pending_review.page_id}><OptionComparison key={session.pending_review.page_id} result={sessionApi.browserPage(session.session_id, session.pending_review)} appearance={appearance} context={session.context} totalPages={(session.committed_pages ?? []).length + 1} busy={!!status} onConfirm={choice => { if (debugReview) { debugStep(choice); return; } void run('Saving selection…', async () => {
        await sessionApi.select(session.session_id, session.pending_review!.page_id, choice);
        await refresh();
      }); }} /></ReviewBoundary> : <PageComposer key={session.active_page?.page_id ?? session.current_page_index} sessionId={session.session_id} assets={session.assets} activePage={session.active_page} pageNumber={session.current_page_index} busy={!!status} onGenerate={async (text, files, revise, title) => { await run('Generating options…', async () => {
        const uploaded = files.length ? (await sessionApi.upload(session.session_id, files)).assets : [];
        const assetIds = files.length ? uploaded.map(asset => asset.asset_id) : session.active_page?.asset_ids ?? [];
        const assets = [...(session.assets ?? []), ...uploaded];
        const activePage = { page_id: session.active_page?.page_id ?? crypto.randomUUID(), page_number: session.current_page_index, text, asset_ids: assetIds, ...(title ? { title } : {}) };
        sessionApi.remember(session.session_id, activePage);
        setSession({ ...session, assets, active_page: activePage });
        if (debugWorkspace) {
          setDebug(await sessionApi.debugStart(session.session_id, text, assetIds, activePage.page_id, title));
          setSession(await sessionApi.load(session.session_id));
          return;
        }
        const page = await sessionApi.generate(session.session_id, text, assetIds, activePage.page_id, revise, title);
        setSession({ ...session, assets, active_page: activePage, pending_review: page });
      }); }} />}
      <label className="studio-controls">Review page<select aria-label="Review page" value={activeReviewId ?? ''} onChange={event => selectReviewPage(event.target.value)}>
        {!currentPageId && <option value="">Page {session.current_page_index} · Composing</option>}
        {(session.committed_pages ?? []).map(page => <option key={page.page_id} value={page.page_id}>Page {page.page_number} · Saved</option>)}
        {currentPageId && <option value={currentPageId}>Page {session.current_page_index} · {session.pending_review ? 'Reviewing options' : 'Composing'}</option>}
      </select></label>
      <ComplianceBanner sessionId={session.session_id} pageId={activeReviewId} snapshot={session} onDecision={refresh} onReport={setCompliance} />
      <DraftViewer sessionId={session.session_id} pages={(session.committed_pages ?? []).map(page => sessionApi.browserPage(session.session_id, page))} context={session.context} appearance={appearance} reviewMetrics={compliance?.ledger} onReviewPage={selectReviewPage} />
    </>}
  </main>;
}
