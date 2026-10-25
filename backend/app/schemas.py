from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
    role: Literal['学员', '付款家长'] = '学员'
    goal: Literal['签约前检查', '付款后核对', '了解退款'] = '签约前检查'
    signed: Literal['未知', '是', '否'] = '未知'
    paid: Literal['未知', '是', '否'] = '未知'
    amount: str = Field(default='', max_length=40)
    signed_date: str = Field(default='', max_length=20)
    paid_date: str = Field(default='', max_length=20)
    services: str = Field(default='', max_length=2000)
    preferences: str = Field(default='', max_length=2000)


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


FACT_LABELS = ['签约主体', '收款主体', '成交金额', '分项价格', '服务期限', '服务内容', '交付标准', '退款条件', '违约责任', '争议解决']


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
