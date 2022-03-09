from __future__ import annotations
from typing import List, Callable, Optional, Dict, Union, TypeVar, Iterable, Tuple
from decimal import Decimal, DefaultContext
from dataclasses import dataclass, field, InitVar
from copy import deepcopy, copy
import itertools
import argparse


_Money = TypeVar('_Money', Tuple[Union[int, Decimal], Union[int, Decimal]], Decimal, int, float, str)

Rate = TypeVar('Rate', Decimal, int)


class Money:
    _CONTEXT = DefaultContext.copy()

    def __init__(self, val: _Money):
        self._val = val
        self._yuan, self._fen = self._cast(val)

    def _cast(self, val: _Money) -> Tuple[Decimal, Decimal]:
        if isinstance(val, str):
            if val == 'inf' or val == '-inf':
                return self.m(val), self.m(0)
            if val.find(".") == -1:
                return self.m(val), self.m(0)
            yuan, fen = val.split('.')
            assert len(fen) <= 2, f"fen must be no more than two digest, {fen} got"
            return self.m(yuan), self.m(fen[:2])
        if isinstance(val, tuple):
            assert len(val) == 2, "tuple must have two items"
            return val[0].quantize(Decimal('1.')), val[1].quantize(Decimal('1.'))
        yuan = self.m(val)
        fen = self.m(val * 100 % 100)
        return yuan, fen

    @classmethod
    def m(cls, val) -> Decimal:
        return Decimal(val, context=cls._CONTEXT)

    @property
    def val(self):
        return self._val

    @property
    def yuan(self):
        return self._yuan

    @property
    def fen(self):
        return self._fen

    @property
    def total_fen(self):
        return self._yuan * 100 + self._fen

    @property
    def is_nan(self):
        return self.yuan.is_nan()

    @property
    def is_inf(self):
        return self.yuan.is_infinite()

    def __str__(self):
        return f'{self.yuan}.{abs(self.fen):0>2}' if not self.is_inf else str(self.yuan)

    def __repr__(self):
        return self.__str__()

    def __hash__(self):
        return int(self.total_fen) if not self.is_inf else 2**32

    def __neg__(self):
        return self.__class__((-self.yuan, -self.fen))

    def __abs__(self):
        return copy(self) if self > 0 else -self

    def __copy__(self):
        return self.__class__((copy(self.yuan), copy(self.fen)))

    def __add__(self, other: Union[_Money, Money]):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        yuan = self.yuan + other.yuan
        fen = self.fen + other.fen
        if fen > 100:
            fen -= 100
            yuan += 1
        return self.__class__((yuan, fen))

    def __radd__(self, other):
        return self + other

    def __sub__(self, other):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        yuan = self.yuan - other.yuan
        fen = self.fen - other.fen
        if fen < 0:
            fen += 100
            yuan -= 1
        return self.__class__((yuan, fen))

    def __rsub__(self, other):
        return -(self - other)

    def __mul__(self, other: Rate):
        assert isinstance(other, (int, Decimal)), f"only can mul by int, Decimal; {other}, {other.__class__.__name__} got"
        yuan = self.yuan * other
        fen = self.fen * other / self.m(100)
        return self.__class__(yuan) + self.__class__(fen)

    def __rmul__(self, other: Rate):
        return self * other

    def __truediv__(self, other: Rate):
        return self.__class__(self.yuan / other) + self.__class__(self.fen / other / self.m(100))

    def __ge__(self, other: Union[_Money, Money]) -> bool:
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        return self.total_fen >= other.total_fen

    def __gt__(self, other: Union[_Money, Money]):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        return self.total_fen > other.total_fen

    def __eq__(self, other: Union[_Money, Money]):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        return self.total_fen == other.total_fen

    def __le__(self, other: Union[_Money, Money]):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        return self.total_fen <= other.total_fen

    def __lt__(self, other: Union[_Money, Money]):
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        return self.total_fen < other.total_fen


def m(s: _Money) -> Money:
    return Money(s)


def r(s: Union[str, int]) -> Rate:
    return Money.m(s)


def is_nan(money: Union[Money, None]) -> bool:
    if isinstance(money, Money):
        return money.is_nan
    return True


def is_inf(money: Union[Money, None]) -> bool:
    if isinstance(money, Money):
        return money.is_inf
    return False


DEFAULT_TAX = {
    m('36_000'): r('0.03'),
    m('144_000'): r('0.10'),
    m('300_000'): r('0.20'),
    m('420_000'): r('0.25'),
    m('660_000'): r('0.30'),
    m('960_000'): r('0.35'),
    m('inf'): r('0.45')
}


@dataclass
class TaxStepRate:
    start: Money = m('0')
    limit: Money = m('inf')
    rate: Rate = r('0')
    quick_sub: Money = field(init=False, default=m('0'))
    next_step: Optional[TaxStepRate] = None

    def calc(self, base: Money) -> Money:
        return base * self.rate - self.quick_sub

    def update_quick_sub(self, quick_sub):
        self.quick_sub = quick_sub

    def pretty(self, func: Callable = print) -> str:
        pretty = f'[{self.start}, {self.limit}) -> *{self.rate} -{self.quick_sub}'
        func(pretty)
        return pretty


@dataclass
class SalaryTaxRate:
    tax_steps: InitVar[List[TaxStepRate]]
    tax_rate: TaxStepRate = field(init=False)
    quick_sub_rate: Rate = field(init=False, default=r('1'))

    def __post_init__(self, tax_steps: List[TaxStepRate]):
        self.tax_rate = cur_tax = tax_steps[0]
        cur_quick_sub = m(0)
        for next_step in tax_steps[1:]:
            cur_tax.next_step = next_step
            cur_quick_sub += cur_tax.limit * (next_step.rate - cur_tax.rate) * self.quick_sub_rate
            next_step.update_quick_sub(cur_quick_sub)
            cur_tax = next_step

    def __iter__(self) -> Iterable[TaxStepRate]:
        cur = self.tax_rate
        while cur is not None:
            yield cur
            cur = cur.next_step

    def get_rate(self, val: Money) -> TaxStepRate:
        tax_rate = self.tax_rate
        while val > tax_rate.limit:
            tax_rate = tax_rate.next_step
        # print(f"get {tax_rate=} for {val=}")
        return tax_rate

    def calc(self, val: Money) -> Money:
        return self.get_rate(val).calc(val)

    def pretty(self, func: Callable = print) -> str:
        return '\n'.join(map(lambda x: x.pretty(func), self))

    @classmethod
    def from_dict(cls, tax_config: Dict[Money, Rate], key_as_limit: bool = True) -> SalaryTaxRate:
        if not key_as_limit:
            raise NotImplementedError
        start = m('0')
        tax_steps = []
        for limit, rate in tax_config.items():
            tax_steps.append(TaxStepRate(start, limit, rate))
            start = limit
        last_limit = tax_steps[-1].limit
        assert is_inf(last_limit) and last_limit > 0, "there should be a infinite limit"
        return cls(tax_steps)


@dataclass
class BonusTaxRate(SalaryTaxRate):
    quick_sub_rate: Rate = field(init=False, default=r('1') / r('12'))

    def __repr__(self):
        return super().__repr__()


@dataclass
class TaxDetail:
    salary: Money = m(0)
    tax: Money = m(0)
    fund: Money = m(0)
    insurance: Money = m(0)
    income: Money = m('nan')

    def __post_init__(self):
        assert self.tax >= 0, f"negative tax: {self=}"
        if is_nan(self.income):
            self.income = self.salary - self.tax - self.fund - self.insurance
        assert self.validate(), str(self)

    def validate(self):
        return self.salary - self.income == self.tax + self.fund + self.insurance

    def pretty(self, func: Callable = print, idx: Optional[int] = None):
        pretty = f"{self.income} = {self.salary} - ({self.fund} + {self.insurance}) - {self.tax}"
        if idx is not None:
            pretty = f"{idx:>2}: {pretty}"
        func(pretty)


@dataclass
class AccTax(TaxDetail):
    tax_base: Money = m(0)
    details: List[TaxDetail] = field(default_factory=list)

    def add(self, detail: TaxDetail):
        self.details.append(detail)
        self.salary += detail.salary
        self.tax += detail.tax
        self.fund += detail.fund
        self.insurance += detail.insurance
        self.income += detail.income

    def pretty(self, func: Callable = print, include_detail: bool = False):
        if not include_detail:
            return super().pretty(func=func)
        for idx, detail in enumerate(self.details, start=1):
            detail.pretty(func=func, idx=idx)
        super().pretty(func=lambda x: func('**:', x))


Salary = Money
Bonus = Money


class Month:
    def __init__(self, val: Union[int, Month]):
        self._val = int(val)

        assert 1 <= self._val <= 12, f"invalid Month {self._val}"

    def __add__(self, other: int) -> Month:
        return self.__class__(self._val + other)

    def __radd__(self, other: int) -> Month:
        return self.__class__(self._val + other)

    def __int__(self):
        return self._val

    def __str__(self):
        return str(self._val)

    def __repr__(self):
        return f'Month({self._val})'


@dataclass
class MonthlySalary:
    month: Month
    salaries: List[Salary] = field(default_factory=list)

    def __post_init__(self):
        assert isinstance(self.month, Month), f"month should be `Month`, but `{type(self.month)}` got!!"

    def get_total(self):
        return sum(self.salaries)


@dataclass
class YearlyPackage:
    monthly_salaries: List[MonthlySalary] = field(default_factory=list)
    bonuses: List[Bonus] = field(default_factory=list)

    def __post_init__(self):
        assert len(self.monthly_salaries) == 12

    @classmethod
    def from_list(cls, salaries: List[Salary], bonuses: Optional[List[Bonus]] = None) -> YearlyPackage:
        monthly_salaries = [MonthlySalary(Month(idx), [salary]) for idx, salary in enumerate(salaries, start=1)]
        bonuses = bonuses if bonuses is not None else []
        return cls(monthly_salaries, bonuses)

    @classmethod
    def from_config(cls, salary_config: List[Tuple[Salary, int]], bonuses: Optional[List[Bonus]] = None) -> YearlyPackage:
        assert sum(map(lambda x: x[1], salary_config)) == 12, "there should be 12 month salaries!"
        monthly_salaries = []
        cur_month = 1
        for salary, months in salary_config:
            monthly_salaries += [MonthlySalary(Month(cur_month + i), [salary]) for i in range(months)]
            cur_month += months
        bonuses = bonuses if bonuses is not None else []
        return cls(monthly_salaries, bonuses)

    def get_salaries(self) -> List[Salary]:
        return [monthly_salary.get_total() for monthly_salary in self.monthly_salaries]

    def get_total_bonus(self) -> Bonus:
        return sum(self.bonuses)


@dataclass
class YearlyTax(AccTax):
    bonus_detail: Optional[TaxDetail] = field(init=False, default=None)

    def add_bonus(self, bonus_detail: TaxDetail):
        assert self.bonus_detail is None, "there only should be one bonus"
        self.bonus_detail = bonus_detail
        self.salary += bonus_detail.salary
        self.tax += bonus_detail.tax
        self.income += bonus_detail.income

    def pretty(self, func: Callable = print, include_detail: bool = False):
        if not include_detail:
            return super().pretty(func=func, include_detail=include_detail)
        for idx, detail in enumerate(self.details, start=1):
            if idx <= 12:
                detail.pretty(func=func, idx=idx)
            else:
                detail.pretty(func=lambda x: func('bs', x))
        if self.bonus_detail:
            self.bonus_detail.pretty(func=lambda x: func(' b', x))
        super().pretty(func=lambda x: func('to:', x))


@dataclass
class Taxpayer:
    salary_tax_rate: SalaryTaxRate = field(default_factory=lambda: SalaryTaxRate.from_dict(DEFAULT_TAX))
    bonus_tax_rate: BonusTaxRate = field(default_factory=lambda: BonusTaxRate.from_dict(DEFAULT_TAX))
    start: Money = m('5000')
    fund_base_limit: Money = m('28017')
    insurance_base_limit: Money = m('28017')
    fund_rate: Rate = r('0.07')
    insurance_rate: Rate = r('0.105')

    def calc_salaries(self, salaries: Union[List[Salary], YearlyPackage], additional_free: Money = m('0'),
                      force_fund_base: Money = m('inf'), force_insurance_base: Money = m('inf'), tax_klass=AccTax) -> Union[AccTax, YearlyTax]:
        if isinstance(salaries, YearlyPackage):
            salaries = salaries.get_salaries()
        assert len(salaries) == 12, "only support one-year monthly salaries"
        acc = tax_klass()
        tax_table = iter(self.salary_tax_rate)
        cur_tax_step = next(tax_table)
        for idx, salary in enumerate(salaries):
            fund_base = min(self.fund_base_limit, force_fund_base, salary)
            insurance_base = min(self.insurance_base_limit, force_insurance_base, salary)
            fund = fund_base * self.fund_rate
            insurance = insurance_base * self.insurance_rate

            acc.tax_base += max(self.start, salary - fund - insurance - additional_free) - self.start
            if acc.tax_base >= cur_tax_step.limit:
                cur_tax_step = next(tax_table)

            tax = cur_tax_step.calc(acc.tax_base) - acc.tax
            acc.add(TaxDetail(
                salary=salary,
                tax=tax,
                fund=fund,
                insurance=insurance
            ))
            assert acc.validate(), "why..."

        return acc

    def calc_bonus(self, bonus: Bonus) -> TaxDetail:
        return TaxDetail(
            salary=bonus,
            tax=self.bonus_tax_rate.calc(bonus)
        )

    def calc_package(self, package: YearlyPackage, additional_free: Money = m('0'),
                     force_fund_base: Money = m('inf'),
                     force_insurance_base: Money = m('inf')) -> YearlyTax:
        yearly_tax = self.calc_salaries(package, additional_free, force_fund_base, force_insurance_base, tax_klass=YearlyTax)
        total_bonus = package.get_total_bonus()
        min_tax = m('inf')
        min_bonus = m('0')
        for bonus in package.bonuses:
            cur_tax = self.salary_tax_rate.calc(total_bonus - bonus + yearly_tax.tax_base) - yearly_tax.tax
            cur_tax += self.calc_bonus(bonus).tax
            if cur_tax < min_tax:
                min_bonus = bonus
                min_tax = cur_tax
        for bonus in package.bonuses:
            if bonus is min_bonus:
                continue
            else:
                yearly_tax.tax_base += bonus
                yearly_tax.add(TaxDetail(bonus, self.salary_tax_rate.calc(yearly_tax.tax_base) - yearly_tax.tax))
        yearly_tax.add_bonus(self.calc_bonus(min_bonus))
        return yearly_tax

    def calc_all_package(self, package: YearlyPackage, additional_free: Money = m('0'),
                         force_fund_base: Money = m('inf'),
                         force_insurance_base: Money = m('inf')) -> Dict[Bonus, YearlyTax]:
        base_yearly_tax = self.calc_salaries(package, additional_free, force_fund_base, force_insurance_base, tax_klass=YearlyTax)
        yearly_taxes = {}
        for as_bonus in itertools.chain([None], package.bonuses):
            yearly_tax = deepcopy(base_yearly_tax)
            for bonus in package.bonuses:
                if bonus is as_bonus:
                    continue
                else:
                    yearly_tax.tax_base += bonus
                    yearly_tax.add(TaxDetail(bonus, self.salary_tax_rate.calc(yearly_tax.tax_base) - yearly_tax.tax))
            if as_bonus is not None:
                yearly_tax.add_bonus(self.calc_bonus(as_bonus))
            yearly_taxes[as_bonus] = yearly_tax
        return yearly_taxes


class SalaryAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        salaries = []
        too_many_salaries_error = ValueError(f'too many salaries, you should have at most 12 month salary in 1 year.')
        for value in values:
            vs = value.split(':')
            if len(salaries) > 11:
                raise too_many_salaries_error
            if len(vs) == 1:
                salaries.append(Salary(vs[0]))
            elif len(vs) == 2:
                salary = Salary(vs[0])
                count = int(vs[1])
                if count > 12 - len(salaries):
                    raise too_many_salaries_error
                for _ in range(count):
                    salaries.append(salary)
            else:
                raise ValueError(f'Invalid Salary: {value}, `salary` or `salary:months` is required')
        setattr(namespace, self.dest, salaries)


class DictAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        kw = getattr(namespace, self.dest)
        key = option_string[2:].replace('-', '_')
        if key in kw:
            raise RuntimeError(f'duplicate key: {key}, current option string: {option_string}')
        kw[key] = values
        setattr(namespace, self.dest, kw)


def main():
    parser = argparse.ArgumentParser(description="A simple tools to calculate tax")
    parser.add_argument('salaries', metavar='Salary', nargs='+', action=SalaryAction)
    parser.add_argument('-b', '--bonus', metavar='Bonus', dest='bonuses', action='append', type=Bonus, default=[])
    parser.add_argument('-d', '--detail', action='store_true')
    parser.add_argument('-a', '--all', action='store_true')
    parser.add_argument('--additional-free', dest='calc_args', action=DictAction, default={}, type=m, metavar='Money')
    parser.add_argument('--force-fund-base', dest='calc_args', action=DictAction, default={}, type=m, metavar='Money')
    parser.add_argument('--force-insurance-base', dest='calc_args', action=DictAction, default={}, type=m, metavar='Money')
    args = parser.parse_args()
    if not args.bonuses:
        if args.all:
            raise ValueError('-a/--all only usable in calcuate package')
        Taxpayer().calc_salaries(args.salaries, **args.calc_args).pretty(include_detail=args.detail)
    else:
        yp = YearlyPackage.from_list(args.salaries, args.bonuses)
        if not args.all:
            Taxpayer().calc_package(yp, **args.calc_args).pretty(include_detail=args.detail)
        else:
            for bonus, yearly_tax in Taxpayer().calc_all_package(yp, **args.calc_args).items():
                if not args.detail:
                    yearly_tax.pretty(lambda *x: print(f'{bonus} as Bonus:', *x))
                else:
                    print('='*10, bonus, 'as Bonus', '=' * 10)
                    yearly_tax.pretty(include_detail=True)


if __name__ == '__main__':
    main()

