from pydantic import BaseModel, Field
from typing import List, Optional

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

class ApplicationVerificationResult(BaseModel):
    destination: str
    documents: List[ExtractedDocument]
    critical_flags: List[str]
    ready_for_submission: bool