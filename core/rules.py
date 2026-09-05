import re
from difflib import SequenceMatcher
from typing import Iterable, List
from .schemas import ExtractedDocument

_COMMON_NAME_FORMS = {
    "alexander": {"alex"},
    "benjamin": {"ben", "benny"},
    "charles": {"charlie", "chuck"},
    "daniel": {"dan", "danny"},
    "elizabeth": {"liz", "beth", "lizzy"},
    "james": {"jim", "jimmy"},
    "jonathan": {"jon", "johnny"},
    "katherine": {"kate", "kathy", "katie"},
    "margaret": {"maggie", "meg", "peggy"},
    "michael": {"mike"},
    "robert": {"bob", "rob", "bobby"},
    "samuel": {"sam", "sammy"},
    "thomas": {"tom", "tommy"},
    "william": {"will", "bill", "billy"},
}

def _normalise(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").split())


def _normalise_address(value: str) -> str:
    address = value.casefold().replace("&", " and ")
    address = re.sub(r"[.,/#()]+", " ", address)
    replacements = {
        " street ": " st ",
        " road ": " rd ",
        " avenue ": " ave ",
        " boulevard ": " blvd ",
        " lane ": " ln ",
        " drive ": " dr ",
        " apartment ": " apt ",
        " flat ": " apt ",
    }
    address = f" {address} "
    for source, target in replacements.items():
        address = address.replace(source, target)
    return " ".join(address.split())


def _addresses_are_similar(first_address: str, second_address: str) -> bool:
    first = _normalise_address(first_address)
    second = _normalise_address(second_address)
    if not first or not second:
        return True
    if first == second:
        return True

    first_tokens = set(first.split())
    second_tokens = set(second.split())
    ignored_tokens = {
        "street", "st", "road", "rd", "avenue", "ave", "boulevard", "blvd",
        "lane", "ln", "drive", "dr", "apartment", "apt", "flat", "unit",
    }
    meaningful_overlap = {
        token for token in first_tokens & second_tokens
        if token not in ignored_tokens and len(token) >= 2
    }
    first_tail = set(first.split()[-5:]) - ignored_tokens
    second_tail = set(second.split()[-5:]) - ignored_tokens
    shared_tail = meaningful_overlap & first_tail & second_tail

    known_places = {
        "india", "ind", "uk", "united", "kingdom", "england", "scotland", "wales",
        "ireland", "usa", "us", "america", "canada", "australia", "germany",
        "france", "spain", "italy", "portugal", "netherlands", "belgium",
        "kerala", "tamil", "karnataka", "maharashtra", "delhi", "london",
        "colchester", "manchester", "birmingham", "edinburgh", "glasgow",
    }
    shared_known_places = (first_tokens & second_tokens) & known_places
    if shared_known_places or len(shared_tail) >= 2:
        return True

    first_postal = _postal_tokens(first)
    second_postal = _postal_tokens(second)
    if first_postal and second_postal and first_postal & second_postal:
        return True

    return False


def _postal_tokens(address: str) -> set[str]:
    return {
        token for token in re.findall(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b|\b\d{5,6}\b", address.upper())
    }

def _is_name_order_swapped(first_name: str, second_name: str) -> bool:
    first_parts = _normalise(first_name).split()
    second_parts = _normalise(second_name).split()
    return len(first_parts) >= 2 and second_parts == list(reversed(first_parts))


def _name_tokens_match(first_token: str, second_token: str) -> bool:
    if first_token == second_token:
        return True
    if len(first_token) == 1 or len(second_token) == 1:
        return first_token[0] == second_token[0]
    if first_token.startswith(second_token) or second_token.startswith(first_token):
        return len(min(first_token, second_token, key=len)) >= 3
    if second_token in _COMMON_NAME_FORMS.get(first_token, set()):
        return True
    if first_token in _COMMON_NAME_FORMS.get(second_token, set()):
        return True
    return len(first_token) >= 4 and len(second_token) >= 4 and SequenceMatcher(
        None, first_token, second_token
    ).ratio() >= 0.86


def _names_are_similar(first_name: str, second_name: str) -> bool:
    first_parts = _normalise(first_name).split()
    second_parts = _normalise(second_name).split()
    if len(first_parts) < 2 or len(first_parts) != len(second_parts):
        return False
    return all(
        _name_tokens_match(first_token, second_token)
        for first_token, second_token in zip(first_parts, second_parts)
    ) or all(
        _name_tokens_match(first_token, second_token)
        for first_token, second_token in zip(first_parts, reversed(second_parts))
    )


def run_cross_validation_rules(
    docs: List[ExtractedDocument],
    jurisdiction: str,
    allowed_names: Iterable[str] = (),
) -> List[str]:
    flags = []
    allowed_name_keys = {_normalise(name) for name in allowed_names if name}
    passports = [d for d in docs if "passport" in d.document_type.lower()]
    passport = passports[0] if passports else None
    
    if not passport:
        if all(document.is_invitee_document for document in docs):
            return _non_identity_flags(docs)
        return ["CRITICAL: Passport document is missing for this applicant."]

    for doc in docs:
        if "passport" in doc.document_type.lower() and doc is not passport:
            continue

        # Identity Verification
        related_names = {
            _normalise(name)
            for name in passport.passport_related_names
            if name
        }
        if doc.applicant_name and passport.applicant_name:
            document_name = _normalise(doc.applicant_name)
            passport_name = _normalise(passport.applicant_name)
            if document_name in allowed_name_keys or document_name in related_names:
                pass
            elif _is_name_order_swapped(doc.applicant_name, passport.applicant_name):
                flags.append(
                    f"INFO: First/last name order swapped in {doc.document_type}: "
                    f"'{doc.applicant_name}' vs passport '{passport.applicant_name}'"
                )
            elif document_name != passport_name and _names_are_similar(doc.applicant_name, passport.applicant_name):
                flags.append(
                    f"INFO: Similar or shortened applicant name in {doc.document_type}: "
                    f"'{doc.applicant_name}' vs passport '{passport.applicant_name}'"
                )
            elif document_name != passport_name:
                flags.append(f"ERROR: Name mismatch in {doc.document_type}: '{doc.applicant_name}' vs '{passport.applicant_name}'")

        passport_number = _normalise(doc.passport_number or "")
        holder_number = _normalise(passport.passport_number or "")
        if passport_number and holder_number and passport_number != holder_number:
            flags.append(
                f"ERROR: Passport number mismatch in {doc.document_type}: "
                f"'{doc.passport_number}' vs '{passport.passport_number}'"
            )

        if doc.address and passport.address and not _addresses_are_similar(doc.address, passport.address):
            flags.append(
                f"ERROR: Address mismatch in {doc.document_type}: "
                f"'{doc.address}' vs '{passport.address}'"
            )

        holder_names = {
            _normalise(name)
            for name in [
                passport.applicant_name,
                *passport.names_on_document,
                *passport.passport_related_names,
            ]
            if name
        }
        document_names = {_normalise(name) for name in [doc.applicant_name, *doc.names_on_document] if name}
        for name in sorted(document_names - holder_names):
            if doc.applicant_name and name == _normalise(doc.applicant_name):
                continue
            if name not in allowed_name_keys and name not in related_names:
                if _is_name_order_swapped(name, passport.applicant_name or ""):
                    flags.append(
                        f"INFO: First/last name order swapped in {doc.document_type}: "
                        f"'{name}' vs passport '{passport.applicant_name}'"
                    )
                elif _names_are_similar(name, passport.applicant_name or ""):
                    flags.append(
                        f"INFO: Similar or shortened name in {doc.document_type}: "
                        f"'{name}' is similar to passport '{passport.applicant_name}'"
                    )
                else:
                    flags.append(f"INFO: New name found in {doc.document_type}: '{name}' is not on the passport")

        flags.extend(
            f"{doc.document_type}: {anomaly}"
            for anomaly in doc.anomalies_detected
        )
        
        # Translation Compliance
        if doc.is_foreign_language and not doc.has_certified_translation:
            flags.append(f"{doc.document_type} lacks an official certified translation.")

    # Jurisdiction-Specific Thresholds
    if jurisdiction.lower() == "schengen":
        insurance = next((d for d in docs if "insurance" in d.document_type.lower()), None)
        # Using financial_balance_eur from schema to represent coverage amount for simplicity
        if not insurance or (insurance.financial_balance_eur or 0) < 30000:
            flags.append("Schengen Rule: Medical coverage must be at least €30,000.")

    return flags


def _non_identity_flags(docs: List[ExtractedDocument]) -> List[str]:
    flags = []
    for doc in docs:
        flags.extend(f"{doc.document_type}: {anomaly}" for anomaly in doc.anomalies_detected)
        if doc.is_foreign_language and not doc.has_certified_translation:
            flags.append(f"{doc.document_type} lacks an official certified translation.")
    return flags