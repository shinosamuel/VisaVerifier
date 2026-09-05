import os
import mimetypes
import time
from difflib import SequenceMatcher
from collections import defaultdict
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event
from typing import Callable, DefaultDict, List
from google import genai
from google.genai import errors
from google.genai import types
import httpx
from dotenv import load_dotenv

load_dotenv()

try:
    from .schemas import ExtractedDocument
except ImportError:
    from schemas import ExtractedDocument

client = genai.Client()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
MODEL_FALLBACKS = (
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-preview-tts",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
)
RETRYABLE_API_CODES = {401, 403, 408, 429, 500, 502, 503, 504}
MAX_SCAN_WORKERS = min(16, max(1, int(os.getenv("SCAN_WORKERS", "8"))))

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic"}
EXCLUDED_DIRECTORIES = {"misc", "invitee"}
GENERATED_REPORT_PREFIX = "visa_verification_report_"
COMMON_NAME_FORMS = {
    "alexander": {"alex"}, "benjamin": {"ben", "benny"}, "charles": {"charlie", "chuck"},
    "daniel": {"dan", "danny"}, "elizabeth": {"liz", "beth", "lizzy"}, "james": {"jim", "jimmy"},
    "jonathan": {"jon", "johnny"}, "katherine": {"kate", "kathy", "katie"},
    "margaret": {"maggie", "meg", "peggy"}, "michael": {"mike"}, "robert": {"bob", "rob", "bobby"},
    "samuel": {"sam", "sammy"}, "thomas": {"tom", "tommy"}, "william": {"will", "bill", "billy"},
}


class ScanCancelledError(Exception):
    """Raised when the user stops a folder scan."""

def extract_document_data(
    file_path: str,
    destination: str,
    invitee_context: str = "",
    is_invitee_document: bool = False,
) -> ExtractedDocument:
    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    document_part = types.Part.from_bytes(
        data=Path(file_path).read_bytes(),
        mime_type=mime_type,
    )
    prompt = (
        f"Analyze this document for a {destination} visa application. "
        f"The filename is '{filename}' and contains the applicant name and document type; "
        "use it as a metadata clue. Extract identity metadata, verify language, "
        "detect certified translations if non-English, and report any inconsistencies. "
        "Extract the passport number when visible, every personal name printed on the document, "
        "and identify passport relationship names such as father, mother, or spouse. "
        "Extract the full address when visible. "
        "For cover letters, declarations, invitation letters, itineraries, employment letters, payslips, tax records, "
        "accommodation evidence, sponsorship evidence, and other supporting documents, identify the document purpose "
        "and audit every visible statement that could affect a visa decision. Check the applicant name, passport number, "
        "address, travel dates, intended duration, destination, stated purpose, employment, income, available funds, "
        "accommodation, sponsor or host identity, relationship, and contact details. Record any missing, contradictory, "
        "unverifiable, expired, unsigned, undated, or materially different information in anomalies_detected. "
        "Pay particular attention to contradictions with the passport or with facts stated elsewhere in the document, "
        "including different dates, amounts, job details, addresses, family relationships, travel purpose, or funding source. "
        "Flag statements that could suggest an intention to work without permission, remain beyond the visa period, "
        "lack genuine temporary intent, rely on unexplained third-party funds, or lack credible return ties. "
        "For every financial document, extract all visible monetary amounts, dates, currencies, account or income periods, "
        "and financial anomalies; do not limit review to bank statements. For bank statements, extract the currency and every visible monthly or statement-period summary. "
        "For each period, extract opening balance, closing balance, total deposits, total withdrawals, "
        "and whether the balance reached zero. List every visible credit/deposit transaction greater than 50000 "
        "from the last three months and every other notable deposit, including date, "
        "amount, description, and whether the deposit appears sudden or unusual. Do not omit a credit "
        "over 50000 because it is not marked sudden. "
        "For payslips, employment letters, tax records, investment statements, pension records, or sponsorship evidence, "
        "record any visible income, regularity, source of funds, missing period, inconsistency, or unexplained amount "
        "in anomalies_detected. "
        "Use empty arrays or null values when this information is not visible; do not invent values. "
        "Documents in the invitee folder are supporting invitee/host documents, not applicant documents. "
        "The invitee's passport is optional and must not be treated as a missing applicant passport. "
        f"Invitee folder context: {invitee_context or 'not available'}"
    )
    
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExtractedDocument,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True,
        ),
    )
    response = None
    last_error = None
    model_names = dict.fromkeys((MODEL_NAME, *MODEL_FALLBACKS))
    for model_name in model_names:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[document_part, prompt],
                    config=config,
                )
                break
            except errors.APIError as error:
                last_error = error
                if error.code not in RETRYABLE_API_CODES:
                    raise
                if attempt == 0 and error.code not in (401, 403):
                    time.sleep(2)
            except httpx.HTTPError as error:
                last_error = error
                if attempt == 0:
                    time.sleep(2)
        if response is not None:
            break

    if response is None:
        raise RuntimeError(
            f"All Gemini models failed, including connection or token errors: {last_error}"
        ) from last_error

    document = ExtractedDocument.model_validate_json(response.text)
    document.source_filename = os.path.basename(file_path)
    document.is_invitee_document = is_invitee_document
    return document


def scan_folder(
    folder_path: str,
    destination: str,
    progress_callback: Callable[[str, int, int], None] | None = None,
    cancel_event: Event | None = None,
) -> DefaultDict[str, List[ExtractedDocument]]:
    _raise_if_cancelled(cancel_event)
    grouped_documents: DefaultDict[str, List[ExtractedDocument]] = defaultdict(list)
    root = Path(folder_path)
    invitee_path = next((path for path in root.iterdir() if path.is_dir() and path.name.casefold() == "invitee"), None)
    invitee_context = ""
    if invitee_path:
        invitee_files = sorted(path.name for path in invitee_path.rglob("*") if path.is_file())
        invitee_context = ", ".join(invitee_files[:30])

    def is_candidate(path: Path, include_invitee: bool = False) -> bool:
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False
        if path.name.casefold().startswith(GENERATED_REPORT_PREFIX):
            return False
        relative_parts = {part.casefold() for part in path.relative_to(root).parts[:-1]}
        excluded = EXCLUDED_DIRECTORIES - ({"invitee"} if include_invitee else set())
        return not relative_parts.intersection(excluded)

    root_paths = sorted(path for path in root.iterdir() if is_candidate(path))
    if not root_paths:
        raise RuntimeError("No supported documents found in the selected folder root.")

    paths = sorted(path for path in root.rglob("*") if is_candidate(path))
    nested_paths = [path for path in paths if path.parent != root]
    invitee_paths = []
    if invitee_path:
        invitee_paths = sorted(
            path for path in invitee_path.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    total_paths = len(root_paths) + len(nested_paths) + len(invitee_paths)

    root_documents = _extract_documents_parallel(
        root_paths,
        destination,
        invitee_context,
        progress_callback,
        "Identifying root document",
        progress_offset=0,
        progress_total=total_paths,
        cancel_event=cancel_event,
    )

    passport_documents = [
        document for document in root_documents
        if "passport" in document.document_type.casefold()
        or "passport" in (document.source_filename or "").casefold()
    ]
    if not passport_documents:
        raise RuntimeError("No passport documents found in the selected folder root.")

    passport_paths = {
        document.source_filename for document in passport_documents
    }
    passport_holder_keys = {
        id(document): _identity_key(document)
        or f"passport:{(document.source_filename or str(index)).casefold()}"
        for index, document in enumerate(passport_documents)
    }
    holders = {
        passport_holder_keys[id(document)]: document
        for document in passport_documents
    }
    for document in passport_documents:
        grouped_documents[passport_holder_keys[id(document)]].append(document)
    root_document_by_name = {
        document.source_filename: document for document in root_documents
    }
    nested_documents, invitee_documents = _extract_document_batches_parallel(
        [
            (nested_paths, False, "Identifying document", len(root_paths)),
            (invitee_paths, True, "Reading invitee document", len(root_paths) + len(nested_paths)),
        ],
        destination,
        invitee_context,
        progress_callback,
        total_paths,
        cancel_event,
    )
    for path, document in zip(nested_paths, nested_documents):
        holder_key = _match_passport_holder(document, holders)
        if holder_key:
            grouped_documents[holder_key].append(document)

    for path in paths:
        if path.name in passport_paths or path.parent != root:
            continue
        document = root_document_by_name[path.name]
        holder_key = _match_passport_holder(document, holders)
        if holder_key:
            grouped_documents[holder_key].append(document)

    if invitee_path:
        for path, document in zip(invitee_paths, invitee_documents):
            invitee_key = _identity_key(document) or f"invitee:{path.stem.casefold()}"
            grouped_documents[invitee_key].append(document)

    return grouped_documents


def _report(
    callback: Callable[[str, int, int], None] | None,
    message: str,
    completed: int = 0,
    total: int = 0,
) -> None:
    if callback:
        callback(message, completed, total)


def _raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise ScanCancelledError()


def _extract_documents_parallel(
    paths: list[Path],
    destination: str,
    invitee_context: str,
    progress_callback: Callable[[str, int, int], None] | None,
    progress_label: str,
    is_invitee_document: bool = False,
    progress_offset: int = 0,
    progress_total: int = 0,
    cancel_event: Event | None = None,
) -> list[ExtractedDocument]:
    if not paths:
        return []

    documents: list[ExtractedDocument | None] = [None] * len(paths)
    worker_count = min(MAX_SCAN_WORKERS, len(paths))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="visa-scan") as executor:
        futures = {
            executor.submit(
                extract_document_data,
                str(path),
                destination,
                invitee_context,
                is_invitee_document,
            ): index
            for index, path in enumerate(paths)
        }
        for completed_count, future in enumerate(as_completed(futures), start=1):
            if cancel_event and cancel_event.is_set():
                for pending_future in futures:
                    pending_future.cancel()
                raise ScanCancelledError()
            index = futures[future]
            try:
                documents[index] = future.result()
            except CancelledError:
                raise ScanCancelledError() from None
            _report(
                progress_callback,
                f"{progress_label} {completed_count}/{len(paths)}: {paths[index].name}",
                progress_offset + completed_count,
                progress_total or len(paths),
            )

            _raise_if_cancelled(cancel_event)

    return [document for document in documents if document is not None]


def _extract_document_batches_parallel(
    batches: list[tuple[list[Path], bool, str, int]],
    destination: str,
    invitee_context: str,
    progress_callback: Callable[[str, int, int], None] | None,
    progress_total: int,
    cancel_event: Event | None = None,
) -> tuple[list[ExtractedDocument], list[ExtractedDocument]]:
    batch_results: list[list[ExtractedDocument | None]] = [
        [None] * len(paths) for paths, _, _, _ in batches
    ]
    tasks = [
        (batch_index, path_index, path, is_invitee, label, offset)
        for batch_index, (paths, is_invitee, label, offset) in enumerate(batches)
        for path_index, path in enumerate(paths)
    ]
    if not tasks:
        return [], []

    completed_by_batch = [0] * len(batches)
    with ThreadPoolExecutor(max_workers=min(MAX_SCAN_WORKERS, len(tasks)), thread_name_prefix="visa-scan") as executor:
        futures = {
            executor.submit(
                extract_document_data,
                str(path),
                destination,
                invitee_context,
                is_invitee,
            ): (batch_index, path_index, path, label, offset)
            for batch_index, path_index, path, is_invitee, label, offset in tasks
        }
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                for pending_future in futures:
                    pending_future.cancel()
                raise ScanCancelledError()
            batch_index, path_index, path, label, offset = futures[future]
            try:
                batch_results[batch_index][path_index] = future.result()
            except CancelledError:
                raise ScanCancelledError() from None
            completed_by_batch[batch_index] += 1
            _report(
                progress_callback,
                f"{label} {completed_by_batch[batch_index]}/{len(batches[batch_index][0])}: {path.name}",
                offset + completed_by_batch[batch_index],
                progress_total,
            )

    _raise_if_cancelled(cancel_event)
    return tuple(
        [document for document in results if document is not None]
        for results in batch_results
    )


def _identity_key(document: ExtractedDocument) -> str:
    return (document.passport_number or document.applicant_name or "").strip().casefold()


def _match_passport_holder(
    document: ExtractedDocument,
    holders: dict[str, ExtractedDocument],
) -> str | None:
    document_number = _normalise_value(document.passport_number)
    document_names = {
        _normalise_value(name)
        for name in [document.applicant_name, *document.names_on_document]
        if name
    }
    filename = (document.source_filename or "").casefold()
    matches = []
    for holder_key, passport in holders.items():
        passport_number = _normalise_value(passport.passport_number)
        passport_names = {
            _normalise_value(name)
            for name in [passport.applicant_name, *passport.names_on_document]
            if name
        }
        if document_number and passport_number and document_number == passport_number:
            matches.append((3, holder_key))
        elif passport.applicant_name and _name_in_filename(passport.applicant_name, filename):
            matches.append((2, holder_key))
        elif document_names.intersection(passport_names):
            matches.append((1, holder_key))
        elif _similar_name_set_match(document_names, passport_names):
            matches.append((1, holder_key))

    if not matches:
        return None
    highest_score = max(score for score, _ in matches)
    best_matches = [key for score, key in matches if score == highest_score]
    return best_matches[0] if len(best_matches) == 1 else None


def _normalise_value(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().replace("-", " ").split())


def _similar_name_set_match(first_names: set[str], second_names: set[str]) -> bool:
    return any(_similar_names(first_name, second_name) for first_name in first_names for second_name in second_names)


def _similar_names(first_name: str, second_name: str) -> bool:
    first_parts = _normalise_value(first_name).split()
    second_parts = _normalise_value(second_name).split()
    if len(first_parts) < 2 or len(first_parts) != len(second_parts):
        return False
    return _name_parts_match(first_parts, second_parts) or _name_parts_match(first_parts, list(reversed(second_parts)))


def _name_parts_match(first_parts: list[str], second_parts: list[str]) -> bool:
    for first_part, second_part in zip(first_parts, second_parts):
        if first_part == second_part:
            continue
        if len(first_part) == 1 or len(second_part) == 1:
            if first_part[0] != second_part[0]:
                return False
            continue
        if first_part.startswith(second_part) or second_part.startswith(first_part):
            if len(min(first_part, second_part, key=len)) >= 3:
                continue
        if second_part in COMMON_NAME_FORMS.get(first_part, set()) or first_part in COMMON_NAME_FORMS.get(second_part, set()):
            continue
        if len(first_part) < 4 or len(second_part) < 4 or SequenceMatcher(
            None, first_part, second_part
        ).ratio() < 0.86:
            return False
    return True


def _name_in_filename(name: str, filename: str) -> bool:
    name_key = "".join(character for character in name.casefold() if character.isalnum())
    filename_key = "".join(character for character in filename if character.isalnum())
    return bool(name_key) and name_key in filename_key