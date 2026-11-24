"""Ordered source spans and locally reconstructed, exhaustively checked grouping.

Offsets use Python Unicode code points in the original input. Blank separators
between legacy source blocks remain separators; spans partition each source block
without changing any source characters. No model-returned body copy is accepted.
"""
import re

from bookgen.domain.compliance import _metric_spans
from bookgen.schemas import AtomicTextBlock, SourceGrouping, SourceMetricAnnotation, SourceSpan


def derive_spans(text, blocks, *, config, ledger=()):
    spans = []
    cursor = 0
    for block in blocks:
        origin = text.find(block.text, cursor)
        if origin < 0:
            raise ValueError("Source block is not an ordered exact slice")
        cursor = origin + len(block.text)
        protected = _metric_spans(block, [m for m in ledger if m.source_block_id == block.block_id])
        boundaries = [match.end() for match in re.finditer(config.sentence_boundary, block.text)]
        boundaries.append(len(block.text))
        start = 0
        for end in sorted(set(boundaries)):
            if end <= start or any(a < end < b for a, b, _ in protected):
                continue
            # Bound long unpunctuated text, preserving exact character slices.
            while end - start > config.max_span_chars:
                cut = start + config.max_span_chars
                crossing = next(((a, b) for a, b, _ in protected if a < cut < b), None)
                if crossing:
                    cut = crossing[0] if crossing[0] > start else crossing[1]
                spans.append(SourceSpan(span_id=f"span_{len(spans) + 1:04d}", start=origin + start,
                    end=origin + cut, text=block.text[start:cut], source_block_id=block.block_id, kind=block.kind))
                start = cut
            if end > start:
                spans.append(SourceSpan(span_id=f"span_{len(spans) + 1:04d}", start=origin + start,
                    end=origin + end, text=block.text[start:end], source_block_id=block.block_id, kind=block.kind))
                start = end
    return spans


def deterministic_grouping(spans):
    groups = []
    previous = None
    for span in spans:
        if span.source_block_id != previous:
            role = "prose" if span.kind == "paragraph" else span.kind
            groups.append({"span_ids": [], "role": role})
            previous = span.source_block_id
        groups[-1]["span_ids"].append(span.span_id)
    return SourceGrouping.model_validate({"groups": groups})


def validate_grouping(response, spans):
    if isinstance(response, str):
        result = SourceGrouping.model_validate_json(response)
    else:
        result = SourceGrouping.model_validate(response)
    if [span_id for group in result.groups for span_id in group.span_ids] != [span.span_id for span in spans]:
        raise ValueError("Grouping must cover each source span once in original order")
    return result


def reconstruct_blocks(text, spans, grouping, original_blocks, ledger, *, word_pattern):
    grouping = validate_grouping(grouping, spans)
    by_id = {span.span_id: span for span in spans}
    origins = {}
    for span in spans:
        origins.setdefault(span.source_block_id, span.start)
    occurrences = []
    for block in original_blocks:
        for start, end, metric in _metric_spans(block, [m for m in ledger if m.source_block_id == block.block_id]):
            occurrences.append((origins[block.block_id] + start, origins[block.block_id] + end, metric.classification))
    blocks = []
    for index, group in enumerate(grouping.groups, start=1):
        start, end = by_id[group.span_ids[0]].start, by_id[group.span_ids[-1]].end
        source = text[start:end]
        annotations = [SourceMetricAnnotation(start=a - start, end=b - start, classification=classification)
            for a, b, classification in occurrences if start <= a < b <= end]
        blocks.append(AtomicTextBlock(block_id=f"blk_{index:02d}", kind=group.role, text=source,
            word_count=len(re.findall(word_pattern, source)), char_count=len(source),
            source_span_ids=group.span_ids, source_start=start, source_end=end, metric_annotations=annotations))
    return blocks
