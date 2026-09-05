from dataclasses import dataclass, field
from statistics import mean
from typing import Callable, DefaultDict, List

from .schemas import BankStatementDeposit, BankStatementPeriod, ExtractedDocument


@dataclass
class FinancialReport:
    holder_name: str
    role: str
    statement_count: int
    currency: str
    balance_consistency: str
    financial_stability: str
    sudden_deposits: List[BankStatementDeposit] = field(default_factory=list)
    large_credit_deposits: List[BankStatementDeposit] = field(default_factory=list)
    zero_balance_periods: List[str] = field(default_factory=list)
    total_deposits: float | None = None
    total_withdrawals: float | None = None
    net_savings: float | None = None
    savings_rate: float | None = None
    warnings: List[str] = field(default_factory=list)


def build_financial_reports(
    grouped_documents: DefaultDict[str, List[ExtractedDocument]],
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> List[FinancialReport]:
    reports = []
    total_groups = len(grouped_documents)
    for group_number, documents in enumerate(grouped_documents.values(), start=1):
        applicant_name = next(
            (document.applicant_name for document in documents if document.applicant_name),
            "Unknown holder",
        )
        bank_documents = [
            document for document in documents if _is_bank_statement(document)
        ]
        role = "Invitee / host" if all(
            document.is_invitee_document for document in documents
        ) else "Applicant"
        periods = [
            period
            for document in bank_documents
            for period in document.bank_statement_periods
        ]
        periods.sort(key=lambda period: period.period)
        deposits = [
            deposit
            for document in bank_documents
            for deposit in document.bank_deposits_last_three_months
        ]
        currency = next(
            (document.bank_currency for document in bank_documents if document.bank_currency),
            "Not available",
        )
        total_deposits = _sum_known(period.total_deposits for period in periods)
        total_withdrawals = _sum_known(period.total_withdrawals for period in periods)
        net_savings = (
            total_deposits - total_withdrawals
            if total_deposits is not None and total_withdrawals is not None
            else None
        )
        savings_rate = (
            net_savings / total_deposits * 100
            if net_savings is not None and total_deposits
            else None
        )
        zero_balance_periods = [
            period.period for period in periods if _period_reached_zero(period)
        ]
        balance_consistency = _balance_consistency(periods)
        financial_stability = _financial_stability(periods)
        warnings = _build_warnings(
            balance_consistency,
            financial_stability,
            deposits,
            zero_balance_periods,
            total_deposits,
            total_withdrawals,
        )
        if not bank_documents:
            warnings.append("No bank statement was found for this applicant.")
        reports.append(
            FinancialReport(
                holder_name=applicant_name,
                role=role,
                statement_count=len(bank_documents),
                currency=currency,
                balance_consistency=balance_consistency,
                financial_stability=financial_stability,
                sudden_deposits=[
                    deposit for deposit in deposits if deposit.is_sudden is True
                ],
                large_credit_deposits=[
                    deposit for deposit in deposits
                    if deposit.amount is not None and deposit.amount > 50000
                ],
                zero_balance_periods=zero_balance_periods,
                total_deposits=total_deposits,
                total_withdrawals=total_withdrawals,
                net_savings=net_savings,
                savings_rate=savings_rate,
                warnings=warnings,
            )
        )
        if progress_callback:
            progress_callback(
                f"Analyzing financial records {group_number}/{total_groups}: {applicant_name}",
                group_number,
                total_groups,
            )
    if progress_callback and not total_groups:
        progress_callback("Financial analysis complete", 1, 1)
    return reports


def _is_bank_statement(document: ExtractedDocument) -> bool:
    document_type = document.document_type.casefold()
    filename = (document.source_filename or "").casefold()
    return "bank" in document_type and "statement" in document_type or (
        "bank" in filename and "statement" in filename
    )


def _sum_known(values) -> float | None:
    known_values = [value for value in values if value is not None]
    return sum(known_values) if known_values else None


def _period_reached_zero(period: BankStatementPeriod) -> bool:
    return period.zero_balance_occurred is True or any(
        balance is not None and balance <= 0
        for balance in (period.opening_balance, period.closing_balance)
    )


def _balance_consistency(periods: List[BankStatementPeriod]) -> str:
    comparisons = []
    for previous, current in zip(periods, periods[1:]):
        if previous.closing_balance is None or current.opening_balance is None:
            continue
        tolerance = max(1.0, abs(previous.closing_balance) * 0.02)
        comparisons.append(abs(previous.closing_balance - current.opening_balance) <= tolerance)
    if not comparisons:
        return "Insufficient history"
    return "Consistent" if all(comparisons) else "Inconsistent"


def _financial_stability(periods: List[BankStatementPeriod]) -> str:
    closing_balances = [
        period.closing_balance
        for period in periods
        if period.closing_balance is not None
    ]
    if len(closing_balances) < 2:
        return "Insufficient history"
    average_balance = mean(closing_balances)
    if average_balance <= 0:
        return "Unstable"
    variation = (max(closing_balances) - min(closing_balances)) / average_balance
    if any(balance < 0 for balance in closing_balances):
        return "Unstable"
    return "Stable" if variation <= 0.35 else "Variable"


def _build_warnings(
    balance_consistency: str,
    financial_stability: str,
    deposits: List[BankStatementDeposit],
    zero_balance_periods: List[str],
    total_deposits: float | None,
    total_withdrawals: float | None,
) -> List[str]:
    warnings = []
    if balance_consistency == "Inconsistent":
        warnings.append("Opening and closing balances do not consistently carry forward.")
    if financial_stability in {"Variable", "Unstable"}:
        warnings.append(f"Financial stability is {financial_stability.casefold()}.")
    if any(deposit.is_sudden is True for deposit in deposits):
        warnings.append("One or more sudden deposits were identified in the last three months.")
    if zero_balance_periods:
        warnings.append("Zero balance occurred in: " + ", ".join(zero_balance_periods) + ".")
    if total_deposits is not None and total_withdrawals is not None and total_withdrawals > total_deposits:
        warnings.append("Withdrawals exceed deposits across the extracted periods.")
    return warnings