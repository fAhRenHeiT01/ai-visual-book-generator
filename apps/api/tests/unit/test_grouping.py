"""Grouping is an ordered pointer partition, never model-authored source copy."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'apps/api/src'))

from bookgen.config import load_settings
from bookgen.domain.compliance import compliance_metrics_scan, mask_blocks
from bookgen.domain.grouping import derive_spans, deterministic_grouping, reconstruct_blocks, validate_grouping
from bookgen.domain.profiler import profile_content
from bookgen.adapters.storage.local_fs import LocalFSStorage
from bookgen.schemas import AtomicTextBlock, MetricClassification


def sources(tmp_path, text):
    settings = load_settings()
    blocks = profile_content(text, storage=LocalFSStorage(tmp_path), settings=settings.profiling).blocks
    ledger = compliance_metrics_scan(blocks, config=settings.compliance)
    spans = derive_spans(text, blocks, config=settings.profiling.grouping, ledger=ledger)
    return settings, blocks, ledger, spans


def test_unicode_repeated_sentences_crlf_and_exact_offsets(tmp_path):
    text = '\u201cCaf\u00e9 \U0001f600 works.\u201d Again. Again.\r\nNext line.\r\n\r\n# Heading\r\n'
    settings, blocks, ledger, spans = sources(tmp_path, text)
    assert [s.text for s in spans[:3]] == ['\u201cCaf\u00e9 \U0001f600 works.\u201d ', 'Again. ', 'Again.\r\n']
    assert all(text[s.start:s.end] == s.text for s in spans)
    assert len({s.span_id for s in spans}) == len(spans)
    assert spans == derive_spans(text, blocks, config=settings.profiling.grouping, ledger=ledger)
    result = reconstruct_blocks(text, spans, deterministic_grouping(spans), blocks, ledger,
        word_pattern=settings.profiling.block_patterns.word)
    assert [b.text for b in result] == [b.text for b in blocks]
    assert all(text[b.source_start:b.source_end] == b.text for b in result)


@pytest.mark.parametrize('payload', [
    {'groups': []},
    {'groups': [{'span_ids': ['span_0001'], 'role': 'prose'}]},
    {'groups': [{'span_ids': ['span_0001', 'span_0001'], 'role': 'quote'}]},
    {'groups': [{'span_ids': ['span_0002', 'span_0001'], 'role': 'quote'}]},
    {'groups': [{'span_ids': ['invented', 'span_0002'], 'role': 'fact'}]},
    {'groups': [{'span_ids': ['span_0001', 'span_0002'], 'role': 'html'}]},
    {'groups': [{'span_ids': ['span_0001', 'span_0002'], 'role': 'prose', 'text': 'edited'}]},
    {'groups': [{'span_ids': [], 'role': 'prose'}]},
    'not JSON', None,
])
def test_grouping_rejects_missing_duplicate_reordered_invented_ids_and_copy(tmp_path, payload):
    _, _, _, spans = sources(tmp_path, 'First. Second.')
    with pytest.raises(ValueError):
        validate_grouping(payload, spans)


def test_sensitivity_stays_bound_to_source_occurrences_after_split_and_merge(tmp_path):
    text = '[INTERNAL] A private claim. Revenue is $4.2M ARR.\n\n[PUBLIC] Revenue is $4.2M ARR.'
    settings, blocks, ledger, spans = sources(tmp_path, text)
    grouping = validate_grouping({'groups': [{'span_ids': [s.span_id], 'role': 'metric'} for s in spans]}, spans)
    result = reconstruct_blocks(text, spans, grouping, blocks, ledger,
        word_pattern=settings.profiling.block_patterns.word)
    new_ledger = compliance_metrics_scan(result, config=settings.compliance)
    assert [m.classification for m in new_ledger] == [MetricClassification.INTERNAL, MetricClassification.PUBLIC]
    assert '$4.2M' not in mask_blocks(result, new_ledger)[1].text
    assert '$4.2M' in mask_blocks(result, new_ledger)[2].text
    # A restart rescans the persisted blocks; annotations retain classification.
    loaded = [AtomicTextBlock.model_validate_json(b.model_dump_json()) for b in result]
    assert compliance_metrics_scan(loaded, config=settings.compliance) == new_ledger
    merged = reconstruct_blocks(text, spans, {'groups': [{'span_ids': [s.span_id for s in spans], 'role': 'prose'}]},
        blocks, ledger, word_pattern=settings.profiling.block_patterns.word)
    assert [m.classification for m in compliance_metrics_scan(merged, config=settings.compliance)] == [MetricClassification.INTERNAL, MetricClassification.PUBLIC]


def test_legacy_blocks_need_no_grouping_metadata():
    old = AtomicTextBlock.model_validate({'block_id': 'previous_id', 'kind': 'paragraph', 'text': 'Original.', 'word_count': 1, 'char_count': 9})
    assert old.block_id == 'previous_id'
    assert old.source_span_ids == []


def test_long_input_span_limits_do_not_cut_metric_occurrences(tmp_path):
    settings, blocks, ledger, _ = sources(tmp_path, '[INTERNAL] Revenue $4.2M ARR and more words')
    settings.profiling.grouping.max_span_chars = 3
    spans = derive_spans(blocks[0].text, blocks, config=settings.profiling.grouping, ledger=ledger)
    assert ''.join(s.text for s in spans) == blocks[0].text
    assert sum('$4.2M' in s.text for s in spans) == 1
