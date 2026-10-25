from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .schemas import StrictModel, EvidenceReference

Money = Annotated[Decimal, Field(ge=0, le=100000000, max_digits=12, decimal_places=2, allow_inf_nan=False)]


class DocRef(StrictModel):
    document_id: str
    version: int = Field(ge=1)


class PromiseRequest(DocRef):
    promises: str = Field(min_length=1, max_length=6000)
    source: str = Field(default='用户提供的销售说法', max_length=200)
    consent: bool = False


class PromiseItem(StrictModel):
    promise_id: int
    status: Literal['合同有写', '说法不一致', '合同没找到', '需要确认']
    explanation: str = Field(max_length=600)
    question: str = Field(max_length=400)
    evidence: list[EvidenceReference] = Field(max_length=6)


class PromiseResult(StrictModel):
    items: list[PromiseItem]


class ServiceCost(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    quantity: Annotated[Decimal, Field(ge=0, le=10000, max_digits=9, decimal_places=4, allow_inf_nan=False)]
    unit_price: Money
    basis: str = Field(min_length=1, max_length=500)


class RefundRequest(StrictModel):
    paid: Money
    already_refunded: Money = Decimal('0')
    services: list[ServiceCost] = Field(default_factory=list, max_length=50)
    penalty_base: Money = Decimal('0')
    penalty_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4, allow_inf_nan=False)] = Decimal('0')
    penalty_basis: str = Field(default='', max_length=500)
    confirmed: bool = False

    @model_validator(mode='after')
    def check_inputs(self):
        if self.already_refunded > self.paid:
            raise ValueError('已退款不能超过实付金额。')
        if self.penalty_rate and (not self.penalty_basis.strip() or not self.penalty_base):
            raise ValueError('请填写违约金计算基数和依据。')
        if not self.confirmed:
            raise ValueError('请先核对计算输入。')
        return self


class SnapshotRef(StrictModel):
    document_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    history_id: str | None = None

    @model_validator(mode='after')
    def exactly_one(self):
        if bool(self.history_id) == bool(self.document_id) or (self.document_id and not self.version):
            raise ValueError('请选择一个明确文档版本。')
        return self


class CompareRequest(StrictModel):
    left: SnapshotRef
    right: SnapshotRef


class SaveRequest(DocRef):
    report_id: str | None = None
    draft: str = Field(default='', max_length=10000)
