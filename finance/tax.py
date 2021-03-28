from __future__ import annotations
from typing import List, Callable, Optional, Dict, Union
from decimal import Decimal, DefaultContext
from dataclasses import dataclass, field, InitVar


context = DefaultContext

def m(s: Union[str, Decimal]) -> Decimal:
    return Decimal(s, context=context)


DEFAULT_TAX = {
    m('36_000'): m('0.03'),
    m('144_000'): m('0.10'),
    m('300_000'): m('0.20'),
    m('420_000'): m('0.25'),
    m('660_000'): m('0.30'),
    m('960_000'): m('0.35'),
    m('inf'): m('0.45')
}


@dataclass
class TaxStepRate:
    start: Decimal = m('0')
    limit: Decimal = m('inf')
    rate: Decimal = m('0')
    quick_sub: Decimal = field(init=False, default=m('0'))
    next_step: Optional[TaxStepRate] = None

    def calc(self, base: Decimal) -> Decimal:
        tax = base * self.rate - self.quick_sub
        return tax

    def update_quick_sub(self, quick_sub):
        self.quick_sub = quick_sub

    def pretty(self, func=print):
        pretty = f'[{self.start}, {self.limit}) -> *{self.rate} -{self.quick_sub}'
        func(pretty)
        return pretty


@dataclass
class SalaryTaxRate:
    tax_steps: InitVar[List[TaxStepRate]]
    tax_rate: TaxStepRate = field(init=False)
    quick_sub_rate: Decimal = field(init=False, default=m('1'))

    def __post_init__(self, tax_steps):
        self.tax_rate = cur_tax = tax_steps[0]
        cur_quick_sub = m(0)
        for next_step in tax_steps[1:]:
            cur_tax.next_step = next_step
            cur_quick_sub += cur_tax.limit * (next_step.rate - cur_tax.rate) * self.quick_sub_rate
            next_step.update_quick_sub(cur_quick_sub)
            cur_tax = next_step

    def __iter__(self):
        cur = self.tax_rate
        while cur is not None:
            yield cur
            cur = cur.next_step

    def pretty(self, func=print):
        return '\n'.join(map(lambda x: x.pretty(func), self))

    @classmethod
    def from_dict(cls, tax_config: Dict[Decimal, Decimal], key_as_limit=True):
        if not key_as_limit:
            raise NotImplementedError
        start = m('0')
        tax_steps = []
        for limit, rate in tax_config.items():
            tax_steps.append(TaxStepRate(start, limit, rate))
            start = limit
        last_limit = tax_steps[-1].limit
        assert Decimal.is_infinite(last_limit) and last_limit > 0, "there should be a infinite limit"
        return cls(tax_steps)


@dataclass
class BonusTaxRate(SalaryTaxRate):
    quick_sub_rate: Decimal = field(init=False, default=m('1') / m('12'))

    def __repr__(self):
        return super().__repr__()


@dataclass
class TaxDetail:
    salary: Decimal = m(0)
    tax: Decimal = m(0)
    fund: Decimal = m(0)
    insurance: Decimal = m(0)
    income: Decimal = m(0)

    def __post_init__(self):
        assert self.validate()

    def validate(self):
        return self.salary - self.income == self.tax + self.fund + self.insurance

    def pretty(self, func=print, idx=None):
        pretty = f"{self.income:.2f} = {self.salary:.2f} - ({self.fund:.2f} + {self.insurance:.2f}) - {self.tax:.2f}"
        if idx is not None:
            pretty = f"{idx:>2}: {pretty}"
        func(pretty)


@dataclass
class AccTax(TaxDetail):
    tax_base: Decimal = m(0)
    details: List[TaxDetail] = field(default_factory=list)

    def add(self, detail: TaxDetail):
        self.details.append(detail)
        self.salary += detail.salary
        self.tax += detail.tax
        self.fund += detail.fund
        self.insurance += detail.insurance
        self.income += detail.income

    def pretty(self, func=print, include_detail=False):
        super().pretty(func=func)
        if not include_detail:
            return
        func("====== detail ======")
        for idx, detail in enumerate(self.details, start=1):
            detail.pretty(func=func, idx=idx)


@dataclass
class Taxpayer:
    salary_tax_rate: SalaryTaxRate = field(default_factory=lambda: SalaryTaxRate.from_dict(DEFAULT_TAX))
    bonus_tax_rate: BonusTaxRate = field(default_factory=lambda: BonusTaxRate.from_dict(DEFAULT_TAX))
    start: Decimal = m('5000')
    fund_base_limit: Decimal = m('28017')
    insurance_base_limit: Decimal = m('28017')
    fund_rate: Decimal = m('0.07')
    insurance_rate: Decimal = m('0.105')


    def calc_salaries(self, salaries: List[Decimal], additional_free: Decimal=m('0'), fund_base: Decimal=m('inf'), insurance_base: Decimal=m('inf')):
        assert len(salaries) == 12
        acc = AccTax()
        tax_table = iter(self.salary_tax_rate)
        cur_tax_step = next(tax_table)
        for idx, salary in enumerate(salaries):
            fund_base = min(self.fund_base_limit, fund_base, salary)
            insurance_base = min(self.insurance_base_limit, fund_base, salary)
            fund = fund_base * self.fund_rate
            insurance = insurance_base * self.insurance_rate

            acc.tax_base += max(self.start, salary - fund - insurance - additional_free) - self.start
            if acc.tax_base >= cur_tax_step.limit:
                cur_tax_step = next(tax_table)

            tax = cur_tax_step.calc(acc.tax_base) - acc.tax
            income = salary - fund - insurance - tax
            acc.add(TaxDetail(
                salary=salary,
                tax=tax,
                fund=fund,
                insurance=insurance,
                income=income
            ))
            assert acc.validate(), "why..."

        return acc


if __name__ == '__main__':
    print('===tax table===')
    SalaryTaxRate.from_dict(DEFAULT_TAX).pretty()
    print('===end table===')
    i = Taxpayer()
    # salaries = [m(10_000)] * 12
    salaries = [m(10_000)] * 2 + [m(12_000)] + [m(12_000) * m('1.3')] * 9
    tax = i.calc_salaries(salaries)
    tax.pretty(include_detail=True)
