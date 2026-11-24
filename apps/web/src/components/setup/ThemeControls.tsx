'use client';
import { useEffect, useId, useRef, useState } from 'react';
import type { components } from '../../types/generated';
import { sessionApi } from '../../lib/sessionApi';
import { PageCanvas } from '../../engine/PageCanvas';
import { PagePreview } from '../studio/PagePreview';

type S = components['schemas'];
type Appearance = S['AppearanceResponse'];
export type ThemeControlsProps = {
  sessionId?: string;
  appearance?: Appearance;
  locked?: boolean;
  onAppearanceChange?: (appearance: Appearance) => void;
};
const swatches = [['color_paper', 'Paper'], ['color_ink_primary', 'Primary ink'], ['color_ink_muted', 'Muted ink'], ['color_brand_primary', 'Brand primary'], ['color_brand_accent', 'Brand accent'], ['color_surface_tint', 'Surface tint']] as const;
const slots = [['header_left', 'Header left'], ['header_right', 'Header right'], ['footer_left', 'Footer left'], ['footer_center', 'Footer center'], ['footer_right', 'Footer right']] as const;
type ColorRole = typeof swatches[number][0];
function validHex(value: unknown): value is string {
  return typeof value === 'string' && value.length === 7 && value[0] === '#' && [...value.slice(1)].every(character => '0123456789abcdef'.includes(character.toLowerCase()));
}
/** WCAG relative luminance; the API owns the configured contrast threshold and sanitation. */
function contrast(foreground: string, background: string) {
  if (!validHex(foreground) || !validHex(background)) return 'unavailable';
  const luminance = (color: string) => [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
  const values = [luminance(foreground), luminance(background)];
  return `${((Math.max(...values) + .05) / (Math.min(...values) + .05)).toFixed(2)}:1`;
}
// Static demonstration copy uses the same pointer contract as authored pages.
const previewBlocks: S['AtomicTextBlock'][] = [
  ['heading', 'Your next chapter'], ['body', 'A clear story, in your colors. Preview the palette, headers, and footers before applying it to this book.'], ['quote', 'Make every page feel like your brand.'], ['stat', '12 chapters, one consistent style.'], ['list', 'Clear titles and generous breathing room.'],
].map(([block_id, text]) => ({ block_id, text, kind: 'paragraph', char_count: text.length, word_count: text.split(' ').length }));
const previewLayout: S['PageLayoutAST'] = {
  option_id: 'theme-preview', archetype: 'minimalist_swiss', strategy_tag: 'theme-preview', rationale: '', surface_role: 'paper', density_scale: 'airy', column_count: 1, surface_treatment: 'brand_panel', emphasis_treatment: 'headline',
  components: [
    { emphasis: false, extracted_excerpt: null, object_fit: 'contain', source_asset_id: null, component_id: 'heading', component_type: 'heading', slot_id: 'header', source_block_ids: ['heading'], surface_role: 'paper' },
    { emphasis: false, extracted_excerpt: null, object_fit: 'contain', source_asset_id: null, component_id: 'rule', component_type: 'divider_rule', slot_id: 'body', source_block_ids: [], surface_role: 'paper' },
    { emphasis: false, extracted_excerpt: null, object_fit: 'contain', source_asset_id: null, component_id: 'body', component_type: 'body_prose', slot_id: 'body', source_block_ids: ['body'], surface_role: 'surface_tint' },
    { emphasis: false, extracted_excerpt: null, object_fit: 'contain', source_asset_id: null, component_id: 'list', component_type: 'bullet_list', slot_id: 'body', source_block_ids: ['list'], surface_role: 'paper' },
    { object_fit: 'contain', source_asset_id: null, component_id: 'stat', component_type: 'stat_callout', slot_id: 'callout', source_block_ids: ['stat'], extracted_excerpt: '12 chapters', surface_role: 'surface_tint', emphasis: true },
    { object_fit: 'contain', source_asset_id: null, component_id: 'quote', component_type: 'pull_quote', slot_id: 'callout', source_block_ids: ['quote'], extracted_excerpt: previewBlocks[2].text, surface_role: 'accent_soft', emphasis: true },
  ],
};
const preview: S['PageGenerationResult'] = { page_id: 'theme-preview', page_number: 1, title: null, input_blocks: previewBlocks, input_assets: [], option_a: previewLayout, option_b: { ...previewLayout, option_id: 'theme-preview-b' }, selected_option_id: 'theme-preview', metrics_ledger: [], repair_attempts: 0, used_fallback: false };

export function ThemeControls({ sessionId, appearance, locked = false, onAppearanceChange }: ThemeControlsProps) {
  const id = useId();
  const [draft, setDraft] = useState(appearance);
  const [themes, setThemes] = useState<S['ThemeLibraryEntry'][]>([]);
  const [selected, setSelected] = useState<string | undefined>(appearance?.tokens.palette_source === 'preset' ? appearance.tokens.theme_id : undefined);
  const [inputs, setInputs] = useState<Partial<Record<ColorRole, string>>>({});
  const [url, setUrl] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState<'extract' | 'apply' | ''>('');
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState('');
  const [reload, setReload] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const operation = useRef(false);
  const cards = useRef<(HTMLButtonElement | null)[]>([]);
  // A generation lock immediately shows the book's persisted appearance.
  const current = locked ? appearance : draft;
  useEffect(() => {
    setDraft(appearance); setInputs({});
    setSelected(appearance?.tokens.palette_source === 'preset' ? appearance.tokens.theme_id : undefined);
  }, [appearance, sessionId, locked]);
  useEffect(() => { setNotice(''); setError(''); }, [sessionId, locked]);
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    setLibraryLoading(true); setLibraryError('');
    sessionApi.themes().then(value => { if (active) setThemes(value.themes ?? []); })
      .catch(failure => { if (active) setLibraryError(failure instanceof Error ? failure.message : 'Could not load theme library.'); })
      .finally(() => { if (active) setLibraryLoading(false); });
    return () => { active = false; };
  }, [sessionId, reload]);
  const disabled = locked || !!busy || !sessionId || !current;
  const paletteReady = !!current && swatches.every(([key]) => validHex(current.tokens[key]));
  const invalid = Object.entries(inputs).filter(([, value]) => !validHex(value));
  function choose(theme: S['ThemeLibraryEntry']) {
    if (disabled || !current) return;
    setSelected(theme.theme_id); setInputs({}); setError(''); setNotice('');
    setDraft({ ...current, tokens: { ...theme.tokens } });
  }
  function editColor(key: ColorRole, value: string) {
    if (disabled || !current) return;
    setInputs(previous => ({ ...previous, [key]: value })); setNotice(''); setError('');
    if (validHex(value)) {
      setSelected(undefined);
      setDraft({ ...current, tokens: { ...current.tokens, [key]: value, palette_source: 'manual' } });
    }
  }
  async function extract() {
    if (disabled || !current || operation.current) return;
    operation.current = true; setBusy('extract'); setError(''); setNotice('');
    try {
      const extracted = await sessionApi.extractTheme(url, name.trim() || undefined);
      if (extracted.status !== 'available' || !extracted.tokens) throw new Error('Could not extract colors. Choose a theme or try another website.');
      setDraft({ ...current, tokens: extracted.tokens }); setInputs({}); setSelected(extracted.theme_id ?? undefined);
      setNotice('Theme saved to library. Inspect the preview, then apply it to this book.');
      setReload(value => value + 1);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Theme extraction failed.'); }
    finally { operation.current = false; setBusy(''); }
  }
  async function apply() {
    if (disabled || invalid.length || !current || !sessionId || operation.current) return;
    operation.current = true; setBusy('apply'); setError(''); setNotice('');
    try {
      const theme = themes.find(value => value.theme_id === selected);
      const unchangedPalette = theme && JSON.stringify(current.tokens) === JSON.stringify(theme.tokens);
      const unchangedChrome = JSON.stringify(current.chrome) === JSON.stringify(appearance?.chrome);
      const value = unchangedPalette && unchangedChrome
        ? await sessionApi.applyTheme(sessionId, theme.theme_id)
        : await sessionApi.saveAppearance(sessionId, { tokens: current.tokens, chrome: current.chrome });
      setDraft(value); setInputs({}); onAppearanceChange?.(value);
      setNotice('Appearance saved. Colors were checked for readable contrast.');
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not apply appearance.'); }
    finally { operation.current = false; setBusy(''); }
  }
  return <aside className="theme-controls studio-controls" data-feature-state={appearance?.status ?? 'unavailable'} aria-label="Theme customization">
    <h2>Theme customization</h2>
    {locked ? <p>Appearance is locked because page 1 creation has started.</p> : <p>Select a theme or edit its colors. Changes stay in this preview until you apply them to this book. Appearance locks when you start creating page 1.</p>}
    {!sessionId && <p>Create a book to choose its appearance.</p>}
    {libraryLoading && <p role="status">Loading theme library...</p>}
    {libraryError && <div role="alert">{libraryError} <button disabled={disabled} onClick={() => setReload(value => value + 1)}>Retry theme library</button></div>}
    {!!themes.length && <div role="radiogroup" aria-label="Theme library" className="theme-library">
      {themes.map((theme, index) => <button key={theme.theme_id} ref={element => { cards.current[index] = element; }} type="button" role="radio" aria-label={theme.name} aria-checked={selected === theme.theme_id} disabled={disabled}
        tabIndex={selected === theme.theme_id || (!themes.some(value => value.theme_id === selected) && index === 0) ? 0 : -1}
        className="theme-card" onClick={() => choose(theme)} onKeyDown={event => {
          let next = index;
          if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % themes.length;
          else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + themes.length) % themes.length;
          else if (event.key === 'Home') next = 0;
          else if (event.key === 'End') next = themes.length - 1;
          else return;
          event.preventDefault(); choose(themes[next]); cards.current[next]?.focus();
        }}>
        <strong>{theme.name}</strong><span className="theme-card-swatches" aria-hidden="true">{swatches.map(([key]) => <span key={key} style={{ backgroundColor: theme.tokens[key] }} />)}</span>
        <small>{theme.source_url ? new URL(theme.source_url).hostname : 'Preset'}</small>
      </button>)}
    </div>}
    <div className="theme-extraction"><label>Theme name (optional)<input value={name} disabled={disabled} onChange={event => setName(event.target.value)} /></label>
      <label>Website URL<input type="url" value={url} disabled={disabled} onChange={event => setUrl(event.target.value)} /></label>
      <button disabled={disabled || !url.trim()} onClick={() => void extract()}>Extract website theme</button></div>
    {current && <div className="theme-editor"><div className="theme-fields"><fieldset disabled={disabled}><legend>Palette roles</legend>
      <div className="theme-role-grid">{swatches.map(([key, label]) => <div className="theme-role" key={key}>
        <span role="img" aria-label={`${label} swatch: ${current.tokens[key]}`} className="theme-swatch" style={{ backgroundColor: current.tokens[key] }} />
        <label>{label}<input type="text" spellCheck={false} autoComplete="off" value={(locked ? current.tokens[key] : inputs[key] ?? current.tokens[key]) ?? ''} aria-invalid={!locked && inputs[key] !== undefined && !validHex(inputs[key]!)} aria-describedby={invalid.some(([role]) => role === key) ? `${id}-invalid` : undefined} onChange={event => editColor(key, event.target.value)} /></label>
      </div>)}</div></fieldset>
      <div className="theme-contrast" aria-live="polite"><h3>Contrast ratios</h3>{swatches.filter(([key]) => key !== 'color_paper' && key !== 'color_surface_tint').map(([key, label]) => <p key={key}>{label} on paper: {contrast(current.tokens[key], current.tokens.color_paper)}; on tint: {contrast(current.tokens[key], current.tokens.color_surface_tint)}</p>)}<p>Colors are checked for readable contrast and may be adjusted when applied.</p></div>
      <fieldset disabled={disabled}><legend>Page headers and footers</legend>
        <label><input type="checkbox" checked={current.chrome.enabled} onChange={event => { setNotice(''); setDraft({ ...current, chrome: { ...current.chrome, enabled: event.target.checked } }); }} />Page headers and footers</label>
        {slots.map(([key, label]) => <label key={key}>{label}<input value={current.chrome[key]} onChange={event => { setNotice(''); setDraft({ ...current, chrome: { ...current.chrome, [key]: event.target.value } }); }} /></label>)}
        <p>Use {'{chapter_title}'}, {'{page_number}'} and {'{total_pages}'} in chrome slots.</p>
      </fieldset></div>
      <figure className="theme-miniature"><figcaption>Draft appearance preview</figcaption>{paletteReady ? <PagePreview><PageCanvas result={preview} tokens={current.tokens} chrome={{ config: current.chrome, chapterTitle: 'Your chapter', pageNumber: 1, totalPages: 1 }} /></PagePreview> : <p>Preview is unavailable until the palette has six valid colors.</p>}</figure>
    </div>}
    <button disabled={disabled || !paletteReady || !!invalid.length} onClick={() => void apply()}>{locked ? 'Save appearance' : 'Apply theme'}</button>
    {busy && <p role="status">{busy === 'extract' ? 'Extracting website theme...' : 'Applying appearance...'}</p>}
    {notice && !busy && <p role="status">{notice}</p>}
    {invalid.length > 0 && !locked && <p role="alert" id={`${id}-invalid`}>Enter # followed by six hexadecimal digits for {invalid.map(([key]) => swatches.find(([role]) => role === key)?.[1]).join(', ')}.</p>}
    {error && <p role="alert">{error}</p>}
  </aside>;
}
