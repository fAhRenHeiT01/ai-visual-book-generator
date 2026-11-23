import re
from pydantic import Field, field_validator
from bookgen.schemas import AudienceMode, MetricClassification

from .base import StrictConfig


class AudiencePolicy(StrictConfig):
    callout_classifications: list[MetricClassification]
    approval_required: list[MetricClassification]


class ComplianceConfig(StrictConfig):
    patterns: list[str] = Field(min_length=1)
    tags: dict[str, MetricClassification] = Field(min_length=1)
    tag_template: str
    classification_priority: list[MetricClassification] = Field(min_length=1)
    default_classification: MetricClassification
    audience_policies: dict[AudienceMode, AudiencePolicy]
    strict_privacy: bool

    @field_validator('patterns')
    @classmethod
    def valid_patterns(cls, patterns):
        for pattern in patterns:
            re.compile(pattern)
        return patterns
