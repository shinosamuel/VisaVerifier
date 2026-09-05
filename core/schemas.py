from pydantic import BaseModel, Field
from typing import List, Optional

class BankStatementPeriod(BaseModel):
    period: str = Field(description="Month or statement period, for example 2026-06")
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    total_deposits: Optional[float] = None
    total_withdrawals: Optional[float] = None
    zero_balance_occurred: Optional[bool] = None


class BankStatementDeposit(BaseModel):
    date: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    is_sudden: Optional[bool] = None


class ExtractedDocument(BaseModel):
    document_type: str = Field(description="E.g., Passport, Bank Statement, Insurance")
    applicant_name: Optional[str]
    passport_number: Optional[str] = None
    address: Optional[str] = None
    names_on_document: List[str] = Field(default_factory=list)
    passport_related_names: List[str] = Field(default_factory=list)
    source_filename: Optional[str] = None
    is_invitee_document: bool = False
    is_foreign_language: bool
    has_certified_translation: bool
    financial_balance_eur: Optional[float]
    anomalies_detected: List[str]
    bank_currency: Optional[str] = None
    bank_statement_periods: List[BankStatementPeriod] = Field(default_factory=list)
    bank_deposits_last_three_months: List[BankStatementDeposit] = Field(default_factory=list)

class ApplicationVerificationResult(BaseModel):
    destination: str
    documents: List[ExtractedDocument]
    critical_flags: List[str]
    ready_for_submission: bool