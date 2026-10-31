from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .profiles import current, cn


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Block(StrictModel):
    id: str
    location: str
    text: str
    source: Literal['file', 'paste', 'user_revision', 'ocr']
    original_text: str | None = None
    status: str = 'extracted'


class Document(StrictModel):
    id: str
    version: int = 1
    name: str
    kind: str
    blocks: list[Block]
    warnings: list[str] = []
    coverage: str
    complete: bool = True


class Context(StrictModel):
    # Options come from the active region profile; empty means its first option.
    role: str = Field(default='', max_length=20)
    goal: str = Field(default='', max_length=20)
    signed: Literal['未知', '是', '否'] = '未知'
    paid: Literal['未知', '是', '否'] = '未知'
    amount: str = Field(default='', max_length=40)
    signed_date: str = Field(default='', max_length=20)
    paid_date: str = Field(default='', max_length=20)
    services: str = Field(default='', max_length=2000)
    preferences: str = Field(default='', max_length=2000)
    # Region-only choices (output language, draft channel and recipient); empty where the region has none.
    output_language: str = Field(default='', max_length=20)
    channel: str = Field(default='', max_length=20)
    recipient: str = Field(default='', max_length=20)

    @model_validator(mode='after')
    def region_options(self):
        options = current().context
        self.role = self.role or options.roles[0]
        self.goal = self.goal or options.goals[0]
        if self.role not in options.roles or self.goal not in options.goals:
            raise ValueError('身份或阅读目标不属于当前地区的选项。')
        for name, allowed in (('output_language', options.languages), ('channel', options.channels), ('recipient', options.recipients)):
            value = getattr(self, name) or (allowed[0] if allowed else '')
            if value and value not in allowed:
                raise ValueError('输出语言或沟通渠道不属于当前地区的选项。')
            setattr(self, name, value)
        return self

    def for_model(self):
        # Fields a region does not use are left out, so the mainland payload is unchanged.
        return self.model_dump(exclude={name for name in ('output_language', 'channel', 'recipient') if not getattr(self, name)})


class AnalysisRequest(StrictModel):
    document_id: str
    version: int
    context: Context = Field(default_factory=Context)
    mode: Literal['demo', 'live']
    consent: bool = False


class Evidence(StrictModel):
    block_id: str
    quote: str = Field(min_length=1)
    location: str


# Mainland labels under the old name for existing imports; validation uses the active profile.
FACT_LABELS = list(cn.FACT_LABELS)


class Fact(StrictModel):
    label: str
    value: str
    evidence: list[Evidence]


class Issue(StrictModel):
    title: str
    level: Literal['高', '中', '低']
    reason: str
    evidence: list[Evidence]
    explanation: str
    impact: str
    status: Literal['明确约定', '表述含糊', '条款冲突', '信息缺失']
    question: str
    negotiation: str


class Report(StrictModel):
    summary: str = Field(max_length=150)
    facts: list[Fact]
    issues: list[Issue]
    questions: list[str] = Field(min_length=3, max_length=5)
    amendments: list[str]
    message: str


class EvidenceReference(StrictModel):
    block_id: str
    quote_id: str


class ModelFact(Fact):
    evidence: list[EvidenceReference]


class ModelIssue(Issue):
    evidence: list[EvidenceReference]


class ModelReport(Report):
    facts: list[ModelFact]
    issues: list[ModelIssue]


class TextInput(StrictModel):
    text: str = Field(min_length=1, max_length=250000)


class Revision(StrictModel):
    version: int
    edits: dict[str, str]
