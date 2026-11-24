"""Deterministic classification, reversible privacy, and promotion policy."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'apps/api/src'))


def block(text, block_id='b1'):
    from bookgen.schemas import AtomicTextBlock
    return AtomicTextBlock(block_id=block_id, text=text, kind='paragraph', word_count=len(text.split()), char_count=len(text))


def test_review_report_exposes_exact_occurrence_offsets_without_changing_legacy_pages():
    from bookgen.domain.compliance import compliance_metrics_scan, compliance_report
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, PageGenerationResult
    from bookgen.schemas.sessions import SessionSnapshot
    blocks = [block('😀 [INTERNAL] 42% YoY versus 42% YoY')]
    metrics = compliance_metrics_scan(blocks)
    a, b = safe_fallback_builder(blocks, [])
    page = PageGenerationResult(page_id='p', page_number=1, input_blocks=blocks, input_assets=[],
        option_a=a, option_b=b, selected_option_id='option_a', metrics_ledger=metrics)
    legacy = page.model_dump(mode='json')
    snapshot = SessionSnapshot(session_id='s', context=BookContext(audience_mode='client_facing'),
        committed_pages=[PageGenerationResult.model_validate(legacy)])
    report = compliance_report(snapshot, decisions={('p', metrics[0].metric_id): 'approve',
        ('p', metrics[1].metric_id): 'redact'})
    assert [(item.source_start, item.source_end, item.decision) for item in report.ledger] == [
        (13, 20, 'approve'), (28, 35, 'redact')]
    for item in report.ledger:
        assert blocks[0].text[item.source_start:item.source_end] == item.metric.raw_value
    assert page.model_dump(mode='json') == legacy
    assert report.publishable_pages[0].input_blocks[0].text == '😀 [INTERNAL] 42% YoY versus [REDACTED]'


def test_scan_classifies_tags_and_preserves_exact_metric_spans():
    from bookgen.domain.compliance import compliance_metrics_scan, mask_blocks, rehydrate_layout
    blocks = [block('[PUBLIC] $4.2M ARR and 42% YoY', 'pub'), block('[INTERNAL] $4.2M ARR', 'int'), block('[CONFIDENTIAL] 42% YoY', 'conf'), block('[UNDISCLOSED] 12 employees', 'und'), block('[DRAFT] 15% growth', 'draft'), block('27% growth', 'unknown')]
    ledger = compliance_metrics_scan(blocks)
    assert [entry.raw_value for entry in ledger[:2]] == ['$4.2M ARR', '42% YoY']
    assert [entry.classification.value for entry in ledger] == ['public', 'public', 'internal', 'internal', 'undisclosed', 'unverified', 'unverified']
    masked = mask_blocks(blocks, ledger)
    assert masked[0].text == blocks[0].text
    assert '$4.2M ARR' not in masked[1].text
    layout = {'components': [{'source_block_ids': ['int'], 'extracted_excerpt': masked[1].text}]}
    assert rehydrate_layout(layout, blocks, ledger)['components'][0]['extracted_excerpt'] == blocks[1].text
    assert blocks[1].text == '[INTERNAL] $4.2M ARR'


@pytest.mark.parametrize('tag,allowed', [('PUBLIC', True), ('INTERNAL', False), ('UNDISCLOSED', False), ('DRAFT', False)])
def test_stat_promotion_uses_classification_not_signoff(tag, allowed):
    from bookgen.domain.compliance import callout_eligible, compliance_metrics_scan
    from bookgen.schemas import AudienceMode
    metric = compliance_metrics_scan([block(f'[{tag}] 42% YoY')])[0]
    metric.approved_for_export = True
    assert callout_eligible(metric, AudienceMode.CLIENT_FACING) is allowed
    assert callout_eligible(metric, AudienceMode.INTERNAL)


def test_injected_detector_and_source_versions():
    from bookgen.domain.compliance import compliance_metrics_scan
    class Detector:
        def detect(self, text):
            return [(0, len(text))]
    assert compliance_metrics_scan([block('eleven employees')], detector=Detector())[0].raw_value == 'eleven employees'
    assert compliance_metrics_scan([block('42%')])[0].metric_id != compliance_metrics_scan([block('Changed 42%')])[0].metric_id


def test_privacy_scrubs_error_text_without_changing_pointer_identifiers():
    from bookgen.domain.compliance import compliance_metrics_scan, mask_payload
    ledger = compliance_metrics_scan([block('[INTERNAL] 1')])
    candidate = {'option_id': 'option_a', 'components': [{'component_id': 'c1', 'source_block_ids': ['b1'], 'extracted_excerpt': '1'}], 'rationale': '1', 'invalid_response': 'Got 1'}
    masked = mask_payload(candidate, ledger)
    assert masked['components'][0]['source_block_ids'] == ['b1']
    assert masked['components'][0]['component_id'] == 'c1'
    assert masked['components'][0]['extracted_excerpt'].startswith('[METRIC_')
    assert masked['invalid_response'].startswith('Got [METRIC_')
    assert mask_payload(masked, ledger) == masked


def test_local_ner_adapter_overlapping_spans_and_tag_precedence():
    from bookgen.domain.compliance import compliance_metrics_scan, PresidioMetricDetector
    class Result:
        start, end = 0, 18
    class Analyzer:
        def analyze(self, **kwargs):
            assert kwargs == {'text': 'eleven employees!', 'entities': ['HEADCOUNT'], 'language': 'en'}
            return [Result()]
    detector = PresidioMetricDetector(Analyzer(), entities=['HEADCOUNT'], language='en')
    # Out-of-range entities must never become source pointers.
    assert compliance_metrics_scan([block('eleven employees!')], detector=detector) == []
    assert compliance_metrics_scan([block('[PUBLIC] [INTERNAL] 42%')])[0].classification.value == 'internal'
    class Overlapping:
        def detect(self, text):
            return [(0, 3), (0, 2), (-1, 2)]
    assert len(compliance_metrics_scan([block('42%')], detector=Overlapping())) == 1


def test_masking_replaces_exact_spans_without_mutating_other_numbers_or_words():
    from bookgen.domain.compliance import compliance_metrics_scan, mask_blocks, compliance_report
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, PageGenerationResult
    from bookgen.schemas.sessions import SessionSnapshot
    blocks = [block('[INTERNAL] Q4: 4 employees and 42 employees, 4 employees')]
    metrics = compliance_metrics_scan(blocks)
    masked = mask_blocks(blocks, metrics)
    assert 'Q4:' in masked[0].text
    assert masked[0].text.count('[METRIC_') == 3
    assert all(f'[METRIC_{metric.metric_id}]' in masked[0].text for metric in metrics)
    with pytest.raises(ValueError, match='source version'):
        mask_blocks([blocks[0].model_copy(update={'text': 'Changed 4 employees'})], metrics)
    a, b = safe_fallback_builder(blocks, [])
    page = PageGenerationResult(page_id='p', page_number=1, input_blocks=blocks, input_assets=[], metrics_ledger=metrics, option_a=a, option_b=b, selected_option_id='option_a')
    snapshot = SessionSnapshot(session_id='s', context=BookContext(audience_mode='client_facing'), committed_pages=[page])
    decisions = {('p', metric.metric_id): ('redact' if index == 0 else 'approve') for index, metric in enumerate(metrics)}
    published = compliance_report(snapshot, decisions=decisions).publishable_pages[0]
    assert published.input_blocks[0].text == '[INTERNAL] Q4: [REDACTED] and 42 employees, 4 employees'
    assert all(metric.context_snippet == published.input_blocks[0].text for metric in published.metrics_ledger)


@pytest.mark.parametrize('excerpt,expected', [
    ('[INTERNAL] 42% YoY versus 42% YoY', '[INTERNAL] [REDACTED] versus 42% YoY'),
    ('42% YoY versus 42% YoY', '[REDACTED] versus 42% YoY'),
    ('versus 42% YoY', 'versus 42% YoY'),
    ('42% YoY', '[REDACTED]'),
])
def test_publishable_excerpt_redacts_source_occurrences_only(excerpt, expected):
    from bookgen.domain.compliance import compliance_metrics_scan, require_export_approval
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.domain.validator import deterministic_validator
    from bookgen.schemas import AudienceMode, BookContext, PageGenerationResult, PlacedComponent
    from bookgen.schemas.sessions import SessionSnapshot
    blocks = [block('[INTERNAL] 42% YoY versus 42% YoY')]
    metrics = compliance_metrics_scan(blocks)
    options = safe_fallback_builder(blocks, [])
    options[0].components.append(PlacedComponent(component_id='quote', component_type='pull_quote',
        slot_id=options[0].components[0].slot_id, source_block_ids=['b1'], extracted_excerpt=excerpt))
    assert deterministic_validator(options, blocks, [], metrics=metrics, audience_mode=AudienceMode.CLIENT_FACING) == []
    page = PageGenerationResult(page_id='p', page_number=1, input_blocks=blocks, input_assets=[],
        metrics_ledger=metrics, option_a=options[0], option_b=options[1], selected_option_id='option_a')
    snapshot = SessionSnapshot(session_id='s', context=BookContext(audience_mode='client_facing'), committed_pages=[page])
    decisions = {('p', metric.metric_id): 'redact' if index == 0 else 'approve' for index, metric in enumerate(metrics)}
    published = require_export_approval(snapshot, decisions=decisions)[0]
    assert published.option_a.components[-1].extracted_excerpt == expected
    assert page.option_a.components[-1].extracted_excerpt == excerpt
    assert blocks[0].text == '[INTERNAL] 42% YoY versus 42% YoY'


def test_validator_allows_exact_public_excerpt_and_blocks_approved_internal():
    from bookgen.domain.compliance import compliance_metrics_scan
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.domain.validator import deterministic_validator
    from bookgen.schemas import AudienceMode, PlacedComponent
    for tag in ('PUBLIC', 'INTERNAL', 'UNDISCLOSED', 'DRAFT'):
        blocks = [block(f'[{tag}] 42% YoY')]
        ledger = compliance_metrics_scan(blocks)
        ledger[0].approved_for_export = True
        options = safe_fallback_builder(blocks, [])
        options[0].components.append(PlacedComponent(component_id='stat', component_type='stat_callout', slot_id=options[0].components[0].slot_id, source_block_ids=['b1'], extracted_excerpt='42% YoY'))
        issues = deterministic_validator(options, blocks, [], metrics=ledger, audience_mode=AudienceMode.CLIENT_FACING)
        assert any(issue.code == 'RESTRICTED_STAT_CALLOUT' for issue in issues) == (tag != 'PUBLIC')
        assert not any(issue.code == 'HALLUCINATED_EXCERPT' for issue in issues)


def test_export_gate_masks_only_redacted_source_and_never_accepts_promotion():
    from bookgen.domain.compliance import compliance_metrics_scan, compliance_report, require_export_approval
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, PageGenerationResult, PlacedComponent
    from bookgen.schemas.sessions import SessionSnapshot
    blocks = [block('[INTERNAL] 42% YoY', 'private'), block('[PUBLIC] 42% YoY', 'public')]
    ledger = compliance_metrics_scan(blocks)
    a, b = safe_fallback_builder(blocks, [])
    a.components.append(PlacedComponent(component_id='quote', component_type='pull_quote', slot_id=a.components[0].slot_id, source_block_ids=['private'], extracted_excerpt='42% YoY'))
    a.rationale = '42% YoY'
    page = PageGenerationResult(page_id='p', page_number=1, input_blocks=blocks, input_assets=[], metrics_ledger=ledger, option_a=a, option_b=b, selected_option_id='option_a')
    snapshot = SessionSnapshot(session_id='s', context=BookContext(audience_mode='client_facing'), committed_pages=[page])
    ledger[0].approved_for_export = True
    with pytest.raises(PermissionError):
        require_export_approval(snapshot)
    decisions = {('p', ledger[0].metric_id): 'redact'}
    published = require_export_approval(snapshot, decisions=decisions)[0]
    assert published.input_blocks[0].text == '[INTERNAL] [REDACTED]'
    assert published.input_blocks[1].text == blocks[1].text
    assert published.option_a.components[-1].extracted_excerpt == '[REDACTED]'
    assert published.option_a.rationale == '[REDACTED]'
    assert blocks[0].text == '[INTERNAL] 42% YoY'
    page.option_a.components[-1].component_type = 'stat_callout'
    assert not compliance_report(snapshot, decisions={('p', ledger[0].metric_id): 'approve'}).eligible


@pytest.mark.parametrize('title,expected', [('Revenue $4.2M ARR', 'Revenue [REDACTED]'), ('$4.2M', '[REDACTED]')])
def test_publishable_title_redacts_metric_metadata_without_mutating_source(title, expected):
    from bookgen.domain.compliance import compliance_metrics_scan, require_export_approval
    from bookgen.domain.fallback import safe_fallback_builder
    from bookgen.schemas import BookContext, PageGenerationResult
    from bookgen.schemas.sessions import SessionSnapshot
    blocks = [block('[INTERNAL] $4.2M ARR')]
    ledger = compliance_metrics_scan(blocks)
    a, b = safe_fallback_builder(blocks, [])
    page = PageGenerationResult(page_id='p', page_number=1, title=title, input_blocks=blocks,
        input_assets=[], metrics_ledger=ledger, option_a=a, option_b=b, selected_option_id='option_a')
    source = SessionSnapshot(session_id='s', context=BookContext(audience_mode='client_facing'), committed_pages=[page])
    published = require_export_approval(source, decisions={('p', ledger[0].metric_id): 'redact'})[0]
    assert published.title == expected
    assert page.title == title
    assert blocks[0].text == '[INTERNAL] $4.2M ARR'


def test_rehydration_is_scoped_and_nonexistent_placeholders_fail_exact_validation():
    from bookgen.domain.compliance import compliance_metrics_scan, mask_blocks, rehydrate_layout
    blocks = [block('[INTERNAL] 42%', 'private'), block('[PUBLIC] 42%', 'public')]
    ledger = compliance_metrics_scan(blocks)
    token = mask_blocks(blocks, ledger)[0].text.split()[-1]
    layout = {'components': [{'source_block_ids': ['public'], 'extracted_excerpt': token}, {'source_block_ids': ['private'], 'extracted_excerpt': token}, {'source_block_ids': ['private'], 'extracted_excerpt': None}]}
    hydrated = rehydrate_layout(layout, blocks, ledger)
    assert hydrated['components'][0]['extracted_excerpt'] == token
    assert hydrated['components'][1]['extracted_excerpt'] == '42%'
    assert hydrated['components'][2]['extracted_excerpt'] is None
    assert rehydrate_layout({'components': [{'source_block_ids': None, 'extracted_excerpt': token}]}, blocks, ledger)['components'][0]['extracted_excerpt'] == token
