"""Region profile shape. Everything region-specific lives in one Profile instance."""
from dataclasses import dataclass, field
from typing import Callable
import re


@dataclass(frozen=True)
class ContextOptions:
    roles: tuple[str, ...]
    goals: tuple[str, ...]
    # Empty tuples mean the region has no such choice and the field must stay empty.
    languages: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    recipients: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    region: str
    name: str
    currency: dict
    # None means this region's model prompt is not finished; live calls are refused.
    system: str | None
    fact_labels: tuple[str, ...]
    redact: Callable[[str], str]
    report_forbidden: re.Pattern
    # Partitions block text into excerpts; the pieces must concatenate back to the input.
    split_sentences: Callable[[str], list[str]]
    context: ContextOptions
    demo: dict
    promise: dict
    legal: dict
    workflow: dict
    messages: dict
    ui: dict = field(default_factory=dict)

    @property
    def ready(self):
        return {'analysis': self.system is not None, 'promises': self.promise.get('system') is not None,
                'legal': bool(self.legal['sources'])}

    def public(self):
        """Only display copy and options; never prompts or redaction internals."""
        return {'region': self.region, 'name': self.name, 'currency': self.currency, 'fact_labels': list(self.fact_labels),
                'context': {'roles': list(self.context.roles), 'goals': list(self.context.goals), 'languages': list(self.context.languages),
                            'channels': list(self.context.channels), 'recipients': list(self.context.recipients)},
                'ready': self.ready, 'ui': self.ui}
