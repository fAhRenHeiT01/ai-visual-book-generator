"""Assembly preserves source copy and recomputes all derived matter and numbering."""
import pytest

from bookgen.config import load_settings
from bookgen.domain.fallback import safe_fallback_builder
from bookgen.schemas import AtomicTextBlock, BookContext, PageGenerationResult
from bookgen.schemas.sessions import SessionSnapshot


def snapshot(count=3):
    pages = []
    for index in range(count):
        text = f'Original body copy {index + 1}.'
        blocks = [AtomicTextBlock(block_id=f'b{index}', kind='paragraph', text=text,
            word_count=len(text.split()), char_count=len(text))]
        a, b = safe_fallback_builder(blocks, [])
        pages.append(PageGenerationResult(page_id=f'p{index}', page_number=index + 1,
            input_blocks=blocks, input_assets=[], metrics_ledger=[], option_a=a, option_b=b,
            selected_option_id='option_a'))
    return SessionSnapshot(session_id='fixture', context=BookContext(title='Annual review'), committed_pages=pages)


def test_deterministic_assembly_reorders_deletes_recalculates_without_mutation():
    from bookgen.domain.assembler import assemble_book
    from bookgen.schemas.export import AssemblyOptions
    source = snapshot()
    original = source.model_dump()
    options = AssemblyOptions(imprint='Copyright notice', preface='Reader introduction',
        appendix='Supporting details', closing_cover=True, section_titles={'p1': 'Results'})
    manifest = assemble_book(source, options=options)
    assert [p.kind for p in manifest.pages] == ['cover', 'imprint', 'preface', 'toc', 'body', 'section', 'body', 'body', 'appendix', 'closing_cover']
    assert manifest == assemble_book(source, options=options)
    assert source.model_dump() == original
    changed = source.model_copy(update={'committed_pages': [source.committed_pages[2], source.committed_pages[1]]})
    revised = assemble_book(changed, options=options)
    assert len(revised.pages) == 9
    assert [p.page_number for p in revised.pages] == list(range(1, 10))
    assert all(p.total_pages == 9 and p.anchor == f'page-{p.page_number}' for p in revised.pages)
    assert len({p.anchor for p in revised.pages}) == 9
    assert [p.result.page_id for p in revised.pages if p.kind == 'body'] == ['p2', 'p1']
    assert all(revised.pages[t.page_number - 1].anchor == t.anchor for t in revised.toc)
    assert [p.kind for p in revised.pages].count('toc') == 1
    assert revised.safety_buffer_percent == load_settings().export.safety_buffer_percent


def test_default_matter_and_invalid_section_tag():
    from bookgen.domain.assembler import assemble_book
    from bookgen.schemas.export import AssemblyOptions
    assert [p.kind for p in assemble_book(snapshot(1)).pages] == ['cover', 'toc', 'body']
    with pytest.raises(ValueError, match='section'):
        assemble_book(snapshot(), options=AssemblyOptions(section_titles={'missing': 'Unknown'}))


def test_source_titles_and_chapters_are_deterministic_without_mutating_copy():
    from bookgen.domain.assembler import assemble_book
    from bookgen.schemas.export import AssemblyOptions
    source = snapshot(4)
    heading = AtomicTextBlock(block_id='heading', kind='heading', text='# Results', word_count=2, char_count=9)
    source.committed_pages[1].input_blocks.append(heading)
    source.committed_pages[3].input_blocks = []
    original = source.model_dump()
    manifest = assemble_book(source)
    body = [page for page in manifest.pages if page.kind == 'body']
    assert [page.title for page in body] == ['Original body copy 1.', '# Results', 'Original body copy 3.', 'Page 4']
    assert [page.chapter_title for page in body] == ['', '# Results', '# Results', '# Results']
    assert [page.expected_text for page in body] == [[block.text for block in page.input_blocks] for page in source.committed_pages]
    assert manifest == assemble_book(source)
    assert source.model_dump() == original
    sectioned = assemble_book(source, options=AssemblyOptions(section_titles={'p1': 'Explicit chapter'}))
    assert [page.chapter_title for page in sectioned.pages if page.kind == 'body'] == ['', 'Explicit chapter', 'Explicit chapter', 'Explicit chapter']
    source.committed_pages[1].title = 'Separate explicit title'
    titled = [page for page in assemble_book(source).pages if page.kind == 'body']
    assert titled[1].title == titled[1].chapter_title == 'Separate explicit title'
    assert titled[1].result.input_blocks[-1].text == '# Results'


def test_ssim_rejects_different_pixels():
    from PIL import Image
    from bookgen.adapters.pdf.playwright_exporter import image_ssim
    white = Image.new('RGB', (100, 100), 'white')
    assert image_ssim(white, white) == 1
    assert image_ssim(white, Image.new('RGB', (100, 100), 'black')) < .1


def test_assembled_matter_uses_light_themed_semantic_treatments_and_retains_appearance():
    from bookgen.domain.assembler import assemble_book
    from bookgen.schemas import MasterChromeConfig
    from bookgen.schemas.export import AssemblyOptions
    from bookgen.schemas.publishing import SessionAppearance
    settings = load_settings()
    appearance = SessionAppearance(tokens=settings.theme.preset_palettes['ocean'],
        chrome=MasterChromeConfig(header_left='Annual review'))
    manifest = assemble_book(snapshot(1), appearance=appearance,
        options=AssemblyOptions(section_titles={'p0': 'Results'}, closing_cover=True))
    assert manifest.tokens == appearance.tokens
    assert manifest.chrome == appearance.chrome
    for page in manifest.pages:
        if page.kind == 'body':
            continue
        layout = page.result.option_a
        assert layout.surface_role == 'paper'
        assert layout.surface_treatment == ('brand_panel' if page.kind in ('cover', 'section', 'closing_cover') else 'tinted_band')
        assert layout.components[0].surface_role == 'paper'
        assert page.result.input_blocks[0].text == page.title
