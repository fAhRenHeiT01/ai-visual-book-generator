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


def test_ssim_rejects_different_pixels():
    from PIL import Image
    from bookgen.adapters.pdf.playwright_exporter import image_ssim
    white = Image.new('RGB', (100, 100), 'white')
    assert image_ssim(white, white) == 1
    assert image_ssim(white, Image.new('RGB', (100, 100), 'black')) < .1
