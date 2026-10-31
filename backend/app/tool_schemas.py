from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .schemas import StrictModel, EvidenceReference
from .profiles import current

Money = Annotated[Decimal, Field(ge=0, le=100000000, max_digits=12, decimal_places=2, allow_inf_nan=False)]


class DocRef(StrictModel):
    document_id: str
    version: int = Field(ge=1)


class PromiseRequest(DocRef):
    promises: str = Field(min_length=1, max_length=6000)
    source: str = Field(default='用户提供的销售说法', max_length=200)
    consent: bool = False
    # Only for regions with a language choice; empty elsewhere so the mainland payload is unchanged.
    output_language: str = Field(default='', max_length=20)

    @model_validator(mode='after')
    def region_language(self):
        allowed = current().context.languages
        self.output_language = self.output_language or (allowed[0] if allowed else '')
        if self.output_language and self.output_language not in allowed:
            raise ValueError('输出语言不属于当前地区的选项。')
        return self


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


Percent = Annotated[Decimal, Field(ge=0, le=100, decimal_places=4, allow_inf_nan=False)]


class Deduction(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    amount: Money
    basis: str = Field(min_length=1, max_length=500)


class DepositRequest(StrictModel):
    """Hong Kong move-out settlement. Every figure is typed by the user; nothing is assumed."""
    deposit: Money
    prepaid_rent: Money = Decimal('0')
    rent_arrears: Money = Decimal('0')
    deductions: list[Deduction] = Field(default_factory=list, max_length=50)
    penalty_type: Literal['none', 'months_rent', 'fixed', 'forfeit_deposit'] = 'none'
    monthly_rent: Money = Decimal('0')
    penalty_months: Annotated[Decimal, Field(ge=0, le=36, decimal_places=2, allow_inf_nan=False)] = Decimal('0')
    penalty_amount: Money = Decimal('0')
    penalty_basis: str = Field(default='', max_length=500)
    confirmed: bool = False

    @model_validator(mode='after')
    def check_inputs(self):
        if self.penalty_type != 'none' and not self.penalty_basis.strip():
            raise ValueError('请填写提前退租罚则的合约依据。')
        if self.penalty_type == 'months_rent' and not (self.monthly_rent and self.penalty_months):
            raise ValueError('按月租计算罚则时，请填写月租和月数。')
        if self.penalty_type == 'fixed' and not self.penalty_amount:
            raise ValueError('请填写罚则金额。')
        if not self.confirmed:
            raise ValueError('请先核对计算输入。')
        return self


class UpfrontRequest(StrictModel):
    """One-off costs before moving in. Shares and rates come from the user or the lease, never defaults."""
    first_rent: Money
    deposit: Money
    stamp_duty_total: Money = Decimal('0')
    stamp_duty_share: Percent = Decimal('0')
    commission_base: Money = Decimal('0')
    commission_rate: Percent = Decimal('0')
    others: list[Deduction] = Field(default_factory=list, max_length=20)
    basis: str = Field(min_length=1, max_length=1000)
    confirmed: bool = False

    @model_validator(mode='after')
    def check_inputs(self):
        if not self.confirmed:
            raise ValueError('请先核对计算输入。')
        return self


class ChecklistRequest(DocRef):
    report_id: str
