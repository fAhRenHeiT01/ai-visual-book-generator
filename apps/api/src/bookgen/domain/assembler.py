"""Pure deterministic assembly; user blocks remain pointers and exact source text."""
from bookgen.config import load_settings
from bookgen.schemas import AtomicTextBlock, MasterChromeConfig, PageGenerationResult, PageLayoutAST, PlacedComponent
from bookgen.schemas.export import AssemblyOptions, PrintManifest, PrintPage, TocEntry
from bookgen.schemas.publishing import SessionAppearance


def _matter(kind, text):
    block = AtomicTextBlock(block_id=f'matter-{kind}', kind='heading', text=text,
        word_count=len(text.split()), char_count=len(text))
    def layout(option):
        return PageLayoutAST(option_id=option, strategy_tag='assembly', archetype='section_divider' if kind in ('cover', 'section', 'closing_cover') else 'safe_flow_fallback',
            rationale='', surface_role='paper', surface_treatment='brand_panel' if kind in ('cover', 'section', 'closing_cover') else 'tinted_band',
            emphasis_treatment='headline' if kind in ('cover', 'section', 'closing_cover') else 'balanced', components=[PlacedComponent(component_id=f'matter-{kind}', component_type='heading', slot_id='header', source_block_ids=[block.block_id])])
    return PageGenerationResult(page_id=f'matter-{kind}', page_number=1, input_blocks=[block], input_assets=[],
        metrics_ledger=[], option_a=layout('option_a'), option_b=layout('option_b'), selected_option_id='option_a')


def assemble_book(snapshot, *, options=None, appearance=None, publishable_pages=None, settings=None):
    settings = settings or load_settings()
    options = options or AssemblyOptions()
    appearance = appearance or SessionAppearance(tokens=settings.theme.preset_palettes[settings.theme.default_preset],
        chrome=MasterChromeConfig())
    bodies = snapshot.committed_pages if publishable_pages is None else publishable_pages
    if set(options.section_titles) - {page.page_id for page in bodies}:
        raise ValueError('Unknown section page')
    rows = []
    chapter = snapshot.context.title
    def matter(kind, text):
        rows.append((kind, text, chapter, _matter(kind, text)))
    matter('cover', snapshot.context.title or 'Untitled book')
    for kind in ('imprint', 'preface'):
        if getattr(options, kind):
            matter(kind, getattr(options, kind))
    matter('toc', 'Contents')
    for body in bodies:
        if body.page_id in options.section_titles:
            chapter = options.section_titles[body.page_id]
            matter('section', chapter)
        # Titles are derived from source text without changing the source block.
        title = next((block.text for block in body.input_blocks if block.kind == 'heading'), f'Page {body.page_number}')
        rows.append(('body', title, chapter, body))
    if options.appendix:
        matter('appendix', options.appendix)
    if options.closing_cover:
        matter('closing_cover', snapshot.context.title or 'Untitled book')
    pages = [PrintPage(kind=kind, anchor=f'page-{index}', title=title, chapter_title=chapter_title,
        page_number=index, total_pages=len(rows), result=result.model_copy(deep=True, update={'page_number': index}),
        expected_text=[block.text for block in result.input_blocks])
        for index, (kind, title, chapter_title, result) in enumerate(rows, 1)]
    toc = [TocEntry(title=page.title, anchor=page.anchor, page_number=page.page_number)
        for page in pages if page.kind in ('section', 'body', 'appendix')]
    for page in pages:
        if page.kind == 'toc':
            page.expected_text += [entry.title for entry in toc]
    return PrintManifest(session_id=snapshot.session_id, context=snapshot.context.model_copy(deep=True),
        tokens=appearance.tokens, chrome=appearance.chrome, pages=pages, toc=toc,
        safety_buffer_percent=settings.export.require_complete().safety_buffer_percent)
