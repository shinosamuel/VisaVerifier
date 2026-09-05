from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .financial_report import FinancialReport
from .scanner import MODEL_FALLBACKS, MODEL_NAME, client

REPORT_TITLE = "Visa Verification Report"


def generate_pdf_report(
    output_path: str | Path,
    destination: str,
    source_folder: str,
    scan_comments: str,
    findings: Iterable[tuple[str, str]],
    financial_reports: list[FinancialReport],
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    findings = list(findings)
    executive_summary = _generate_executive_summary(
        destination,
        scan_comments,
        findings,
        financial_reports,
    )
    styles = _build_styles()
    story = [
        Paragraph(REPORT_TITLE, styles["ReportTitle"]),
        Paragraph(
            f"Prepared {datetime.now().strftime('%d %B %Y, %H:%M')} | Route: {_safe(destination)}",
            styles["ReportSubtitle"],
        ),
        Spacer(1, 8),
        _section_heading("Executive summary", styles),
        Paragraph(_safe(executive_summary).replace("\n", "<br/>"), styles["Body"]),
        Spacer(1, 10),
        _section_heading("Scan comments", styles),
        Paragraph(_safe(scan_comments).replace("\n", "<br/>"), styles["Body"]),
        Spacer(1, 10),
        _section_heading("Verification findings", styles),
        _section_heading("Errors and critical issues", styles),
        _findings_table(_findings_by_severity(findings, informational=False), styles),
        Spacer(1, 8),
        _section_heading("Informational findings", styles),
        _findings_table(_findings_by_severity(findings, informational=True), styles),
        Spacer(1, 12),
        _section_heading("Financial statement details", styles),
    ]
    if financial_reports:
        for report in financial_reports:
            story.extend(_financial_section(report, styles))
    else:
        story.append(Paragraph("No financial reports were generated.", styles["Body"]))
    story.extend(
        [
            Spacer(1, 12),
            Paragraph(f"Source folder: {_safe(source_folder)}", styles["Footnote"]),
            Paragraph(
                "This report is an automated review aid and does not replace official visa guidance or professional advice.",
                styles["Footnote"],
            ),
        ]
    )

    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=REPORT_TITLE,
        author="Visa Document Verifier",
    )
    document.build(story, onFirstPage=_draw_page_header, onLaterPages=_draw_page_header)
    return output


def _generate_executive_summary(
    destination: str,
    scan_comments: str,
    findings: Iterable[tuple[str, str]],
    financial_reports: list[FinancialReport],
) -> str:
    finding_lines = "\n".join(f"{applicant}: {finding}" for applicant, finding in findings)
    financial_lines = "\n\n".join(_financial_text(report) for report in financial_reports)
    prompt = (
        "Create a concise professional executive summary for a visa document verification report. "
        "Use only the supplied facts. Do not invent documents, amounts, names, conclusions, or legal advice. "
        "Mention the number and seriousness of verification findings, missing bank statements, and any credits "
        "over 50,000. Use plain text with exactly three short sections titled SUMMARY, KEY RISKS, and EVIDENCE GAPS. "
        "Use one clear point per line and keep each section concise.\n\n"
        f"Visa route: {destination}\n"
        f"Scan comments:\n{scan_comments}\n\n"
        f"Verification findings:\n{finding_lines or 'None'}\n\n"
        f"Financial statement details:\n{financial_lines or 'None'}"
    )
    response = None
    last_error = None
    for model_name in dict.fromkeys((MODEL_NAME, *MODEL_FALLBACKS)):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as error:
            last_error = error
    if last_error:
        return "Automated executive summary was unavailable. Refer to the detailed scan comments, findings, and financial sections below."
    return "No executive summary was returned. Refer to the detailed sections below."


def _financial_text(report: FinancialReport) -> str:
    large_credits = "; ".join(
        _deposit_text(deposit, report.currency)
        for deposit in report.large_credit_deposits
    ) or "None"
    return (
        f"{report.holder_name} ({report.role}); statements: {report.statement_count}; "
        f"stability: {report.financial_stability}; warnings: {'; '.join(report.warnings) or 'None'}; "
        f"credits over 50,000: {large_credits}"
    )


def _financial_section(report: FinancialReport, styles):
    rows = [
        ["Applicant / role", f"{report.holder_name} / {report.role}"],
        ["Statements and currency", f"{report.statement_count} / {report.currency}"],
        ["Balance consistency", report.balance_consistency],
        ["Financial stability", report.financial_stability],
        ["Total deposits", _money(report.total_deposits, report.currency)],
        ["Withdrawals", _money(report.total_withdrawals, report.currency)],
        ["Net savings", _money(report.net_savings, report.currency)],
        ["Savings rate", "Not available" if report.savings_rate is None else f"{report.savings_rate:.1f}%"],
        ["Zero-balance periods", ", ".join(report.zero_balance_periods) or "None identified"],
        ["Credits over 50,000", _credit_lines(report)],
        ["Sudden deposits", _sudden_deposit_lines(report)],
        ["Financial risks and evidence gaps", _warning_lines(report)],
    ]
    table = Table(
        [
            [
                Paragraph(_safe(label), styles["TableLabel"]),
                Paragraph(
                    value if label in {"Credits over 50,000", "Sudden deposits", "Financial risks and evidence gaps"} else _safe(value),
                    styles["TableCell"],
                ),
            ]
            for label, value in rows
        ],
        colWidths=[48 * mm, 128 * mm],
        repeatRows=0,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F4")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D2DA")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return [table, Spacer(1, 10)]


def _findings_table(findings: Iterable[tuple[str, str]], styles):
    rows = [[Paragraph("Applicant", styles["TableHeader"]), Paragraph("Finding", styles["TableHeader"])]]
    findings = list(findings)
    if findings:
        rows.extend(
            [Paragraph(_safe(applicant), styles["TableCell"]), Paragraph(_safe(finding), styles["TableCell"])]
            for applicant, finding in findings
        )
    else:
        rows.append([Paragraph("All applicants", styles["TableCell"]), Paragraph("No findings reported.", styles["TableCell"])])
    table = Table(rows, colWidths=[52 * mm, 124 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D2DA")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F8FA")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _findings_by_severity(
    findings: Iterable[tuple[str, str]],
    informational: bool,
) -> list[tuple[str, str]]:
    selected = []
    for applicant, finding in findings:
        finding_text = str(finding).casefold().lstrip("• ").strip()
        is_info = finding_text.startswith("info")
        if is_info == informational:
            selected.append((applicant, finding))
    return selected


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.HexColor("#17324D"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#5D6D7E"), alignment=TA_CENTER))
    styles.add(ParagraphStyle("ReportSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor("#17324D"), spaceBefore=4, spaceAfter=6))
    styles.add(ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=colors.HexColor("#263238")))
    styles.add(ParagraphStyle("TableHeader", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.white))
    styles.add(ParagraphStyle("TableLabel", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.HexColor("#17324D")))
    styles.add(ParagraphStyle("TableCell", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#263238")))
    styles.add(ParagraphStyle("Footnote", parent=styles["BodyText"], fontName="Helvetica-Oblique", fontSize=7.5, leading=10, textColor=colors.HexColor("#6B7280")))
    return styles


def _section_heading(title: str, styles):
    return Paragraph(title, styles["ReportSection"])


def _draw_page_header(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D5A928"))
    canvas.setLineWidth(1.2)
    canvas.line(document.leftMargin, A4[1] - 11 * mm, A4[0] - document.rightMargin, A4[1] - 11 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    canvas.drawRightString(A4[0] - document.rightMargin, 9 * mm, f"Page {document.page}")
    canvas.restoreState()


def _deposit_text(deposit, currency: str) -> str:
    date = deposit.date or "Date unavailable"
    amount = _money(deposit.amount, currency)
    description = f" ({deposit.description})" if deposit.description else ""
    return f"{date}: {amount}{description}"


def _credit_lines(report: FinancialReport) -> str:
    if not report.large_credit_deposits:
        return "None identified"
    return "<br/>".join(
        f"- {_safe(_deposit_text(deposit, report.currency))}"
        for deposit in report.large_credit_deposits
    )


def _sudden_deposit_lines(report: FinancialReport) -> str:
    if not report.sudden_deposits:
        return "None identified"
    return "<br/>".join(
        f"- {_safe(_deposit_text(deposit, report.currency))}"
        for deposit in report.sudden_deposits
    )


def _warning_lines(report: FinancialReport) -> str:
    if not report.warnings:
        return "None identified"
    return "<br/>".join(f"- {_safe(warning)}" for warning in report.warnings)


def _money(value, currency: str) -> str:
    return "Not available" if value is None else f"{currency} {value:,.2f}"


def _safe(value) -> str:
    return html.escape(str(value or ""), quote=False)
