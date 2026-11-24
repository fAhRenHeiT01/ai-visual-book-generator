"""Local metrics ledger, provider privacy boundary, and authoritative export gate.

Source blocks never change. Metric identifiers bind decisions to exact source text,
classification and occurrence. An injected detector can wrap Presidio's analyze()
without introducing an external model or a download into the deterministic scan.
"""
from typing import Protocol
from copy import deepcopy
from hashlib import sha256
import re

from bookgen.config import load_settings
from bookgen.schemas import ComponentType, MetricClassification, MetricEntry
from bookgen.schemas.publishing import ComplianceMetric, ComplianceReport


class MetricDetector(Protocol):
    def detect(self, text: str) -> list[tuple[int, int]]: ...


class PresidioMetricDetector:
    """Adapter for a caller-owned, locally configured Presidio analyzer."""
    def __init__(self, analyzer, *, entities, language):
        self.analyzer, self.entities, self.language = analyzer, entities, language

    def detect(self, text):
        return [(result.start, result.end) for result in self.analyzer.analyze(
            text=text, entities=self.entities, language=self.language)]


def _source_version(block, start, end, classification):
    return sha256(f'{block.block_id}\0{block.text}\0{start}\0{end}\0{classification.value}'.encode()).hexdigest()


def compliance_metrics_scan(blocks, *, config=None, detector: MetricDetector | None = None):
    config = config or load_settings().compliance
    ledger = []
    for block in blocks:
        tagged = {classification for tag, classification in config.tags.items() if config.tag_template.format(tag=tag).casefold() in block.text.casefold()}
        classification = next((value for value in config.classification_priority if value in tagged), config.default_classification)
        spans = {(match.start(), match.end()) for pattern in config.patterns for match in re.finditer(pattern, block.text, re.IGNORECASE)}
        if detector is not None:
            spans.update(detector.detect(block.text))
        end_of_previous = 0
        for start, end in sorted(spans, key=lambda span: (span[0], -span[1])):
            if not 0 <= start < end <= len(block.text) or start < end_of_previous:
                continue
            end_of_previous = end
            # Grouping can separate a metric from its sensitivity tag. Locally
            # bound annotations carry the original occurrence's classification.
            source_classification = next((annotation.classification for annotation in block.metric_annotations
                if annotation.start == start and annotation.end == end), classification)
            version = _source_version(block, start, end, source_classification)
            ledger.append(MetricEntry(metric_id=version, source_block_id=block.block_id,
                raw_value=block.text[start:end], context_snippet=block.text, classification=source_classification))
    return ledger


def callout_eligible(metric, audience_mode, *, config=None):
    config = config or load_settings().compliance
    return metric.classification in config.audience_policies[audience_mode].callout_classifications


def _restricted(ledger):
    return [metric for metric in ledger if metric.classification != MetricClassification.PUBLIC]


def _placeholder(metric):
    return f'[METRIC_{metric.metric_id}]'


def mask_blocks(blocks, ledger):
    return [block.model_copy(update={'text': _mask_block(block, [m for m in _restricted(ledger) if m.source_block_id == block.block_id])}) for block in blocks]


def _metric_spans(block, metrics):
    """Recover exact occurrence offsets locally without changing public schemas."""
    spans = []
    for metric in metrics:
        start = block.text.find(metric.raw_value)
        while start >= 0:
            end = start + len(metric.raw_value)
            if _source_version(block, start, end, metric.classification) == metric.metric_id:
                spans.append((start, end, metric))
                break
            start = block.text.find(metric.raw_value, start + 1)
        else:
            raise ValueError('Metric source version does not match source block')
    return spans


def _mask_block(block, metrics, *, redaction=False):
    text = block.text
    for start, end, metric in sorted(_metric_spans(block, metrics), key=lambda span: span[0], reverse=True):
        replacement = '[REDACTED]' if redaction else _placeholder(metric)
        text = text[:start] + replacement + text[end:]
    return text


def _redact_excerpt(excerpt, source_ids, blocks, metrics):
    """Project source occurrences into a validated excerpt's character offsets.

    The pointer schema has no excerpt offset. When an excerpt occurs more than
    once, mask the union of redactions from its possible source occurrences.
    """
    ranges = []
    for block in blocks:
        if block.block_id not in source_ids:
            continue
        spans = _metric_spans(block, [metric for metric in metrics if metric.source_block_id == block.block_id])
        origin = block.text.find(excerpt)
        while origin >= 0:
            for start, end, _ in spans:
                start, end = max(0, start - origin), min(len(excerpt), end - origin)
                if start < end:
                    ranges.append((start, end))
            origin = block.text.find(excerpt, origin + 1)
    merged = []
    for start, end in sorted(set(ranges)):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        excerpt = excerpt[:start] + '[REDACTED]' + excerpt[end:]
    return excerpt


def _mask_text(text, metrics, *, redaction=False):
    replacements = {metric.raw_value: '[REDACTED]' if redaction else _placeholder(metric) for metric in metrics}
    if not replacements:
        return text
    placeholders = [_placeholder(metric) for metric in metrics]
    pattern = '|'.join(re.escape(value) for value in placeholders + sorted(replacements, key=len, reverse=True))
    return re.sub(pattern, lambda match: replacements.get(match.group(), match.group()), text)


def mask_payload(payload, ledger):
    """Conservatively scrub all free text, including provider errors and traces."""
    if isinstance(payload, str):
        return _mask_text(payload, _restricted(ledger))
    if isinstance(payload, list):
        return [mask_payload(item, ledger) for item in payload]
    if isinstance(payload, dict):
        structural = {'option_id', 'component_id', 'slot_id', 'source_block_ids', 'source_asset_id',
            'asset_id', 'storage_key', 'thumbnail_key', 'archetype', 'component_type', 'surface_role',
            'object_fit', 'density_scale', 'strategy_tag', 'code', 'severity', 'target_option'}
        return {key: value if key in structural else mask_payload(value, ledger) for key, value in payload.items()}
    return payload


def rehydrate_layout(layout, blocks, ledger):
    result = deepcopy(layout)
    components = result.get('components', [])
    if not isinstance(components, list):
        return result
    source_ids = {block.block_id for block in blocks}
    for component in components:
        if not isinstance(component, dict):
            continue
        excerpt = component.get('extracted_excerpt')
        if not isinstance(excerpt, str) or not excerpt:
            continue
        ids = component.get('source_block_ids', [])
        if not isinstance(ids, list):
            continue
        for metric in _restricted(ledger):
            if metric.source_block_id in ids and metric.source_block_id in source_ids:
                excerpt = excerpt.replace(_placeholder(metric), metric.raw_value)
        # Validation verifies this against exact original source, never provider copy.
        component['extracted_excerpt'] = excerpt
    return result


def compliance_report(session_snapshot, *, decisions=None, config=None):
    config = config or load_settings().compliance
    decisions = decisions or {}
    snapshot = session_snapshot
    policy = config.audience_policies[snapshot.context.audience_mode]
    pages = snapshot.committed_pages + ([snapshot.pending_review] if snapshot.pending_review else [])
    ledger = []
    publishable = []
    locked = not snapshot.committed_pages or snapshot.pending_review is not None
    for page in pages:
        metrics = compliance_metrics_scan(page.input_blocks, config=config)
        if page.selected_option_id:
            selected = getattr(page, page.selected_option_id)
            if any(component.component_type == ComponentType.STAT_CALLOUT and
                any(metric.source_block_id in component.source_block_ids and
                    not callout_eligible(metric, snapshot.context.audience_mode, config=config)
                    for metric in metrics) for component in selected.components):
                locked = True
        redactions = []
        for metric in metrics:
            decision = decisions.get((page.page_id, metric.metric_id))
            metric.approved_for_export = decision == 'approve'
            ledger.append(ComplianceMetric(page_id=page.page_id, metric=metric, decision=decision))
            if metric.classification in policy.approval_required and decision not in ('approve', 'redact'):
                locked = True
            if decision == 'redact':
                redactions.append(metric)
        copy = page.model_copy(deep=True)
        # Inferred titles can end within a metric at the configured word limit.
        # Project source offsets first, then scrub explicit metadata matches.
        if copy.title:
            copy.title = _mask_text(_redact_excerpt(copy.title, [block.block_id for block in page.input_blocks],
                page.input_blocks, redactions), redactions, redaction=True)
        for block in copy.input_blocks:
            block.text = _mask_block(block, [m for m in redactions if m.source_block_id == block.block_id], redaction=True)
            block.char_count, block.word_count = len(block.text), len(block.text.split())
        for option in (copy.option_a, copy.option_b):
            option.rationale = _mask_text(option.rationale, redactions, redaction=True)
            for component in option.components:
                if component.extracted_excerpt:
                    component.extracted_excerpt = _redact_excerpt(component.extracted_excerpt,
                        component.source_block_ids, page.input_blocks, redactions)
        published_text = {block.block_id: block.text for block in copy.input_blocks}
        copy.metrics_ledger = [metric.model_copy(update={
            'raw_value': '[REDACTED]' if metric in redactions else metric.raw_value,
            'context_snippet': published_text[metric.source_block_id]}) for metric in metrics]
        if page.selected_option_id:
            publishable.append(copy)
    return ComplianceReport(status='available', ledger=ledger, eligible=not locked,
        audience_mode=snapshot.context.audience_mode, publishable_pages=publishable if not locked else [])


def require_export_approval(session_snapshot, *, decisions=None, config=None):
    """Reusable server gate: return only approved publishable copies or refuse."""
    report = compliance_report(session_snapshot, decisions=decisions, config=config)
    if not report.eligible:
        raise PermissionError('Export requires committed pages and compliance review')
    return report.publishable_pages
