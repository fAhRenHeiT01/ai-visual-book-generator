'use client';
import { useEffect, useState } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
type Appearance = components['schemas']['AppearanceResponse'];
export type ThemeControlsProps = {
  sessionId?: string;
  appearance?: Appearance;
  locked?: boolean;
  onAppearanceChange?: (appearance: Appearance) => void;
};
export function ThemeControls({ sessionId, appearance, locked = false, onAppearanceChange }: ThemeControlsProps) {
  const [draft, setDraft] = useState(appearance);
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  useEffect(() => { setDraft(appearance); setSaved(false); }, [appearance]);
  const disabled = locked || busy || !sessionId || !draft;
  async function extract() {
    if (disabled || !draft) return;
    setBusy(true); setError(''); setSaved(false);
    try {
      const extracted = await sessionApi.extractTheme(url);
      if (extracted.status !== 'available' || !extracted.tokens) throw new Error('Could not extract colors. Choose a preset or edit the swatches.');
      setDraft({ ...draft, tokens: extracted.tokens });
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Theme extraction failed.'); }
    finally { setBusy(false); }
  }
  async function save() {
    if (disabled || !draft || !sessionId) return;
    setBusy(true); setError(''); setSaved(false);
    try {
      const value = await sessionApi.saveAppearance(sessionId, { tokens: draft.tokens, chrome: draft.chrome });
      setDraft(value); onAppearanceChange?.(value); setSaved(true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not save appearance.'); }
    finally { setBusy(false); }
  }
  const swatches = [['color_paper', 'Paper'], ['color_ink_primary', 'Primary ink'], ['color_ink_muted', 'Muted ink'], ['color_brand_primary', 'Brand primary'], ['color_brand_accent', 'Brand accent'], ['color_surface_tint', 'Surface tint']] as const;
  const slots = [['header_left', 'Header left'], ['header_right', 'Header right'], ['footer_left', 'Footer left'], ['footer_center', 'Footer center'], ['footer_right', 'Footer right']] as const;
  return <aside className="theme-controls studio-controls" data-feature-state={appearance?.status ?? 'unavailable'}>
    <h2>Theme customization</h2>
    {locked && <p>Appearance is locked for this book.</p>}
    <label>Website URL<input type="url" value={url} disabled={disabled} onChange={event => setUrl(event.target.value)} /></label>
    <button disabled={disabled || !url} onClick={() => void extract()}>Extract website theme</button>
    {draft && <>
      <label>Palette preset<input value={draft.tokens.palette_source === 'preset' ? draft.tokens.theme_id : ''} disabled={disabled} placeholder="Configured preset name" onChange={event => { setSaved(false); setDraft({ ...draft, tokens: { ...draft.tokens, theme_id: event.target.value, palette_source: 'preset' } }); }} /></label>
      {swatches.map(([key, label]) => <label key={key}>{label}<input type="color" value={draft.tokens[key]} disabled={disabled} onChange={event => { setSaved(false); setDraft({ ...draft, tokens: { ...draft.tokens, [key]: event.target.value, palette_source: 'manual' } }); }} /></label>)}
      <label><input type="checkbox" checked={draft.chrome.enabled} disabled={disabled} onChange={event => setDraft({ ...draft, chrome: { ...draft.chrome, enabled: event.target.checked } })} />Page headers and footers</label>
      {slots.map(([key, label]) => <label key={key}>{label}<input value={draft.chrome[key]} disabled={disabled} onChange={event => { setSaved(false); setDraft({ ...draft, chrome: { ...draft.chrome, [key]: event.target.value } }); }} /></label>)}
      <p>Use {'{chapter_title}'}, {'{page_number}'} and {'{total_pages}'} in chrome slots.</p>
    </>}
    <button disabled={disabled} onClick={() => void save()}>Save appearance</button>
    {saved && <p role="status">Appearance saved. Colors were checked for readable contrast.</p>}
    {error && <p role="alert">{error}</p>}
  </aside>;
}
