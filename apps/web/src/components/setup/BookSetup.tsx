'use client';
import { useState } from 'react';
import type { components } from '../../types/generated';

type Context = components['schemas']['BookContext'];
export function BookSetup({ busy, onCreate }: { busy: boolean; onCreate: (context: Context) => void }) {
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [tone, setTone] = useState('');
  const [audience, setAudience] = useState<Context['audience_mode']>('internal');
  const [direction, setDirection] = useState<Context['direction']>('auto');
  const [size, setSize] = useState<Context['page_size']>('A4');
  return <form className="setup-form" onSubmit={event => { event.preventDefault(); onCreate({ title, objective, direction, tone_keywords: tone.split(',').map(word => word.trim()).filter(Boolean), audience_mode: audience, page_size: size, source_website_url: null }); }}>
    <div className="section-heading"><p className="eyebrow">01 / Book setup</p><h2>Start a book</h2></div><p>Setup is optional. Add your words and images one page at a time.</p>
    <fieldset disabled={busy} className="setup-fields"><label>Book title (optional)<input value={title} onChange={event => setTitle(event.target.value)} /></label>
    <label>Objective (optional)<textarea value={objective} onChange={event => setObjective(event.target.value)} /></label>
    <label>Tone keywords (optional, comma separated)<input value={tone} onChange={event => setTone(event.target.value)} /></label>
    <label>Audience<select value={audience} onChange={event => setAudience(event.target.value as Context['audience_mode'])}><option value="internal">Internal</option><option value="client_facing">Client facing</option></select></label>
    <label>Page size<select value={size} onChange={event => setSize(event.target.value as Context['page_size'])}><option value="A4">A4</option><option value="LETTER">US Letter</option></select></label>
    <label>Book direction<select value={direction} onChange={event => setDirection(event.target.value as Context['direction'])} aria-describedby="direction-help"><option value="auto">Auto</option><option value="brand_led_editorial">Brand led editorial</option><option value="consulting_report">Consulting report</option><option value="campaign_presentation">Campaign presentation</option></select></label>
    <p id="direction-help" className="field-help">Auto chooses a direction from your brief. Each page explores two layouts within your book direction.</p>
    <button disabled={busy}>Create book</button></fieldset>
  </form>;
}
