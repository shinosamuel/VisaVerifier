import tkinter as tk
import threading
import sys
import os
from datetime import datetime
from threading import Event
from tkinter import ttk, filedialog
from pathlib import Path
from textwrap import fill

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.financial_report import FinancialReport, build_financial_reports
from core.pdf_report import generate_pdf_report
from core.rules import run_cross_validation_rules
from core.scanner import ScanCancelledError, scan_folder

class VisaAppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Visa Document Verifier")
        self.root.geometry("1180x720")
        self.root.minsize(900, 600)
        self.root.state("zoomed")
        self.set_window_icon()
        self.folder_path = None
        self.scan_cancel_event = None
        self.last_scan_comments = ""
        self.last_scan_findings = []
        self.last_financial_reports = []
        self.setup_styles()
        self.create_menu_bar()
        self.create_tool_bar()

        header = ttk.Frame(root, style="Header.TFrame", padding=(24, 18, 24, 16))
        header.pack(fill="x")
        ttk.Label(header, text="Visa Document Verifier", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Review applicant documents and cross-check identity details in one place.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        control_frame = ttk.Frame(root, padding=(24, 14, 24, 10))
        control_frame.pack(fill="x")
        ttk.Button(control_frame, text="Browse folder", command=self.load_folder).pack(side="left")
        self.jurisdiction_var = tk.StringVar(value="Schengen")
        ttk.Label(control_frame, text="Visa route").pack(side="left", padx=(24, 8))
        ttk.Combobox(
            control_frame,
            textvariable=self.jurisdiction_var,
            values=["Schengen", "UK Visit", "Canada Visitor"],
            state="readonly",
            width=18,
        ).pack(side="left")
        self.run_button = ttk.Button(control_frame, text="Run scan", command=self.run_audit, style="Accent.TButton")
        self.run_button.pack(
            side="left", padx=(12, 0)
        )
        self.report_button = ttk.Button(
            control_frame,
            text="Generate PDF report",
            command=self.generate_report,
            state="disabled",
        )
        self.report_button.pack(side="left", padx=(8, 0))
        self.folder_label = ttk.Label(control_frame, text="No folder selected", style="Muted.TLabel")
        self.folder_label.pack(side="left", padx=(18, 0), fill="x", expand=True)

        summary = ttk.Frame(root, padding=(24, 0, 24, 16))
        summary.pack(fill="x")
        self.document_count = self.create_stat(summary, "Documents", "0")
        self.applicant_count = self.create_stat(summary, "Applicants", "0")
        self.issue_count = self.create_stat(summary, "Findings", "0")

        status_bar = ttk.Frame(root, padding=(24, 6), relief="sunken")
        status_bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="Ready - select a folder to begin")
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left", fill="x", expand=True
        )
        self.status_progress = ttk.Progressbar(status_bar, mode="determinate", maximum=100, length=260)
        self.status_progress.pack(side="right", padx=(12, 0))

        body = ttk.Notebook(root)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 10))

        verification_tab = ttk.Frame(body)
        financial_report_tab = ttk.Frame(body)
        body.add(verification_tab, text="Verification")
        body.add(financial_report_tab, text="Financial report")

        verification_body = ttk.Panedwindow(verification_tab, orient="vertical")
        verification_body.pack(fill="both", expand=True)
        documents_frame = ttk.LabelFrame(verification_body, text="Documents found", padding=10)
        comments_frame = ttk.LabelFrame(verification_body, text="Scan comments", padding=10)
        verification_body.add(documents_frame, weight=1)
        verification_body.add(comments_frame, weight=1)

        columns = ("Document", "Applicant (passport)", "Language / translation", "Findings")
        self.tree = ttk.Treeview(documents_frame, columns=columns, show="headings", height=12)
        self.tree.tag_configure("error", foreground="#c0392b")
        self.tree.tag_configure("info", foreground="#d97706")
        self.tree.tag_configure("ok", foreground="#216e4e")
        for col in columns:
            self.tree.heading(col, text=col)
        self.tree.column("Document", width=240, anchor="w")
        self.tree.column("Applicant (passport)", width=200, anchor="w")
        self.tree.column("Language / translation", width=170, anchor="w")
        self.tree.column("Findings", width=560, anchor="w")
        tree_scroll = ttk.Scrollbar(documents_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        self.comments = tk.Text(
            comments_frame,
            height=5,
            wrap="word",
            relief="flat",
            padx=10,
            pady=8,
            background="#f7f8fa",
            foreground="#354052",
            font=("Segoe UI", 10),
        )
        self.comments.pack(fill="both", expand=True)
        self.comments.configure(state="disabled")
        self.create_financial_report_tab(financial_report_tab)

    def create_financial_report_tab(self, parent):
        report_body = ttk.Panedwindow(parent, orient="vertical")
        report_body.pack(fill="both", expand=True, padx=10, pady=10)

        report_frame = ttk.LabelFrame(report_body, text="Financial overview", padding=10)
        details_frame = ttk.LabelFrame(report_body, text="Financial statement details", padding=10)
        report_body.add(report_frame, weight=1)
        report_body.add(details_frame, weight=1)

        columns = (
            "Holder", "Role", "Statements", "Currency", "Balance consistency",
            "Stability", "Sudden deposits", "Credits > 50,000", "Zero balance", "Net savings",
        )
        self.financial_report_tree = ttk.Treeview(report_frame, columns=columns, show="headings")
        for column in columns:
            self.financial_report_tree.heading(column, text=column)
        widths = {
            "Holder": 180, "Role": 120, "Statements": 80, "Currency": 80,
            "Balance consistency": 145, "Stability": 105, "Sudden deposits": 115,
            "Credits > 50,000": 125,
            "Zero balance": 105, "Net savings": 120,
        }
        for column, width in widths.items():
            self.financial_report_tree.column(column, width=width, anchor="w")
        report_scroll = ttk.Scrollbar(report_frame, orient="vertical", command=self.financial_report_tree.yview)
        self.financial_report_tree.configure(yscrollcommand=report_scroll.set)
        self.financial_report_tree.pack(side="left", fill="both", expand=True)
        report_scroll.pack(side="right", fill="y")

        self.financial_report_details = tk.Text(
            details_frame,
            height=9,
            wrap="word",
            relief="flat",
            padx=10,
            pady=8,
            background="#f7f8fa",
            foreground="#354052",
            font=("Segoe UI", 10),
        )
        self.financial_report_details.pack(fill="both", expand=True)
        self.financial_report_details.configure(state="disabled")

    def populate_financial_report(self, reports):
        for item_id in self.financial_report_tree.get_children():
            self.financial_report_tree.delete(item_id)
        if not reports:
            self.set_financial_report_details(
                "No financial statement documents were identified for applicants or invitees."
            )
            return

        detail_sections = []
        for report in reports:
            self.financial_report_tree.insert(
                "", "end",
                values=(
                    report.holder_name,
                    report.role,
                    report.statement_count,
                    report.currency,
                    report.balance_consistency,
                    report.financial_stability,
                    len(report.sudden_deposits),
                    len(report.large_credit_deposits),
                    len(report.zero_balance_periods),
                    self.format_money(report.net_savings, report.currency),
                ),
            )
            detail_sections.append(self.format_financial_report(report))
        self.set_financial_report_details("\n\n".join(detail_sections))

    def format_financial_report(self, report: FinancialReport):
        lines = [
            f"{report.holder_name} ({report.role})",
            f"Statements scanned: {report.statement_count}",
            f"Balance consistency: {report.balance_consistency}",
            f"Financial stability: {report.financial_stability}",
            f"Total deposits: {self.format_money(report.total_deposits, report.currency)}",
            f"Total spending / withdrawals: {self.format_money(report.total_withdrawals, report.currency)}",
            f"Net savings: {self.format_money(report.net_savings, report.currency)}",
            f"Savings rate: {self.format_percentage(report.savings_rate)}",
                "Sudden deposits in last three months:\n"
                + (self.format_deposit_lines(report.sudden_deposits, report.currency)
                    if report.sudden_deposits else "None identified"),
                "Credits over 50,000 in last three months:\n"
                + (self.format_deposit_lines(report.large_credit_deposits, report.currency)
                    if report.large_credit_deposits else "None identified"),
            "Zero-balance periods: "
            + (", ".join(report.zero_balance_periods) if report.zero_balance_periods else "None identified"),
        ]
        if report.warnings:
            lines.append("Warnings:\n- " + "\n- ".join(report.warnings))
        else:
            lines.append("Warnings: None")
        return "\n".join(lines)

    def set_financial_report_details(self, message):
        self.financial_report_details.configure(state="normal")
        self.financial_report_details.delete("1.0", "end")
        self.financial_report_details.insert("1.0", message)
        self.financial_report_details.configure(state="disabled")

    def format_money(self, value, currency):
        if value is None:
            return "Not available"
        return f"{currency} {value:,.2f}"

    def format_percentage(self, value):
        return "Not available" if value is None else f"{value:.1f}%"

    def format_deposit(self, deposit, currency):
        date = deposit.date or "date unavailable"
        amount = self.format_money(deposit.amount, currency)
        description = f" ({deposit.description})" if deposit.description else ""
        return f"{date}: {amount}{description}"

    def format_deposit_lines(self, deposits, currency):
        return "\n".join(f"- {self.format_deposit(deposit, currency)}" for deposit in deposits)

    def set_window_icon(self):
        icon = tk.PhotoImage(width=16, height=16)
        icon.put("#17324d", to=(2, 1, 14, 15))
        icon.put("#0d2438", to=(3, 2, 13, 14))
        icon.put("#eaf0f4", to=(5, 3, 11, 13))
        icon.put("#d5a928", to=(6, 6, 10, 10))
        icon.put("#b58512", to=(7, 5, 9, 11))
        icon.put("#ffffff", to=(4, 4, 5, 12))
        self.root.iconphoto(True, icon)
        self.window_icon = icon

    def create_menu_bar(self):
        menu_bar = tk.Menu(self.root)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Browse folder", command=self.load_folder, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu_bar.add_cascade(label="File", menu=file_menu)

        scan_menu = tk.Menu(menu_bar, tearoff=False)
        scan_menu.add_command(label="Run scan", command=self.run_audit, accelerator="F5")
        scan_menu.add_command(label="Clear results", command=self.clear_results)
        menu_bar.add_cascade(label="Scan", menu=scan_menu)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(label="About", command=lambda: self.set_comments(
            "Visa Document Verifier\n\nSelect a folder, choose a visa route, and run a scan."
        ))
        menu_bar.add_cascade(label="Help", menu=help_menu)

        self.root.configure(menu=menu_bar)
        self.root.bind("<Control-o>", lambda event: self.load_folder())
        self.root.bind("<F5>", lambda event: self.run_audit())

    def create_tool_bar(self):
        toolbar = ttk.Frame(self.root, padding=(24, 8), relief="raised")
        toolbar.pack(fill="x")
        open_button = ttk.Button(toolbar, text="📂", command=self.load_folder, width=3)
        open_button.pack(side="left", padx=(0, 8))
        self.add_tooltip(open_button, "Choose the folder containing visa documents")

        scan_button = ttk.Button(toolbar, text="▶", command=self.run_audit, style="Accent.TButton", width=3)
        scan_button.pack(side="left", padx=8)
        self.add_tooltip(scan_button, "Scan and verify the selected documents")

        self.stop_scan_button = ttk.Button(toolbar, text="■", command=self.stop_scan, width=3, state="disabled")
        self.stop_scan_button.pack(side="left", padx=8)
        self.add_tooltip(self.stop_scan_button, "Stop the current scan")

        clear_button = ttk.Button(toolbar, text="✕", command=self.clear_results, width=3)
        clear_button.pack(side="left", padx=8)
        self.add_tooltip(clear_button, "Clear the current results")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Label(toolbar, text="Tip: Ctrl+O opens a folder, F5 runs a scan", style="Muted.TLabel").pack(side="left")

    def add_tooltip(self, widget, text):
        tooltip = None

        def show(_event):
            nonlocal tooltip
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.configure(background="#263238")
            tooltip.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
            tk.Label(
                tooltip,
                text=text,
                background="#263238",
                foreground="#ffffff",
                padx=8,
                pady=4,
                font=("Segoe UI", 9),
            ).pack()

        def hide(_event):
            nonlocal tooltip
            if tooltip is not None:
                tooltip.destroy()
                tooltip = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def setup_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#ffffff", foreground="#263238")
        style.configure("Header.TFrame", background="#17324d")
        style.configure("Title.TLabel", background="#17324d", foreground="#ffffff", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#17324d", foreground="#c7d7e8", font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground="#6b7280")
        style.configure("Accent.TButton", foreground="#ffffff", background="#167d73", padding=(14, 7))
        style.map("Accent.TButton", background=[("active", "#12665e")])
        style.configure("Treeview", rowheight=48, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview", foreground="#263238")
        style.configure("Treeview.Heading", background="#eaf0f4", foreground="#34495e", font=("Segoe UI", 9, "bold"))
        style.configure("TLabelframe.Label", foreground="#17324d", font=("Segoe UI", 10, "bold"))

    def create_stat(self, parent, label, value):
        frame = ttk.Frame(parent, padding=(14, 9), relief="solid", borderwidth=1)
        frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        value_label = ttk.Label(frame, text=value, font=("Segoe UI", 16, "bold"), foreground="#17324d")
        value_label.pack(anchor="w")
        ttk.Label(frame, text=label, style="Muted.TLabel").pack(anchor="w")
        return value_label

    def load_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.folder_path = folder_path
            self.root.title(f"Visa Document Verifier - {Path(folder_path).name}")
            self.folder_label.configure(text=folder_path)
            self.clear_results()
            self.status_var.set("Folder selected - ready to scan")
            self.set_comments("Folder selected. Choose a visa route and run the scan.")

    def run_audit(self):
        if not self.folder_path:
            self.show_error("Select a folder before running the audit.")
            return

        self.clear_results()
        self.set_comments("Starting scan...")
        self.status_var.set("Scanning documents...")
        self.status_progress.configure(value=0)
        self.run_button.configure(state="disabled")
        self.stop_scan_button.configure(state="normal")
        self.scan_cancel_event = Event()

        def report_progress(message, completed, total):
            progress_value = (completed / total * 100) if total else 0
            self.root.after(0, self.update_scan_progress, message, progress_value)

        def scan_in_background():
            try:
                grouped_documents = scan_folder(
                    self.folder_path,
                    self.jurisdiction_var.get(),
                    progress_callback=report_progress,
                    cancel_event=self.scan_cancel_event,
                )
            except ScanCancelledError:
                self.root.after(0, self.finish_scan_cancelled)
                return
            except Exception as error:
                self.root.after(0, self.finish_scan_error, error)
                return
            self.root.after(0, self.finish_scan, grouped_documents)

        threading.Thread(target=scan_in_background, name="visa-scan", daemon=True).start()

    def update_scan_progress(self, message, progress_value):
        if self.scan_cancel_event is None or self.scan_cancel_event.is_set():
            return
        self.set_comments(message)
        self.status_var.set(message)
        self.status_progress.configure(value=progress_value)

    def finish_scan_error(self, error):
        self.run_button.configure(state="normal")
        self.stop_scan_button.configure(state="disabled")
        self.scan_cancel_event = None
        self.status_var.set("Scan failed")
        self.show_error(f"Scan failed: {error}")

    def finish_scan_cancelled(self):
        self.run_button.configure(state="normal")
        self.stop_scan_button.configure(state="disabled")
        self.scan_cancel_event = None
        self.status_var.set("Scan stopped")
        self.status_progress.configure(value=0)
        self.set_comments("Scan stopped. No partial results were displayed.")

    def stop_scan(self):
        if self.scan_cancel_event is None:
            return
        self.scan_cancel_event.set()
        self.stop_scan_button.configure(state="disabled")
        self.status_var.set("Stopping scan...")
        self.set_comments("Stopping scan and cancelling pending documents...")

    def finish_scan(self, grouped_documents):
        self.run_button.configure(state="normal")
        self.stop_scan_button.configure(state="disabled")
        self.scan_cancel_event = None

        if not grouped_documents:
            self.status_var.set("Scan finished - no documents found")
            self.show_error("No supported documents found in the selected folder.")
            return

        self.status_var.set("Analyzing financial records...")
        self.set_comments("Analyzing financial records...")
        self.status_progress.configure(value=0)
        self.root.update_idletasks()
        financial_reports = build_financial_reports(
            grouped_documents,
            progress_callback=self.update_financial_progress,
        )
        self.last_financial_reports = financial_reports
        self.populate_financial_report(financial_reports)
        total_documents = 0
        total_findings = 0
        applicant_group_count = 0
        comments = []
        all_findings = []
        invitee_names = [
            name
            for documents in grouped_documents.values()
            for document in documents
            if document.is_invitee_document
            for name in [document.applicant_name, *document.names_on_document]
            if name
        ]
        for applicant_documents in grouped_documents.values():
            is_applicant_group = any(
                not document.is_invitee_document
                and "passport" in document.document_type.casefold()
                for document in applicant_documents
            )
            if is_applicant_group:
                applicant_group_count += 1
            flags = run_cross_validation_rules(
                applicant_documents,
                self.jurisdiction_var.get(),
                allowed_names=invitee_names,
            )
            numbered_flags = [
                self.number_finding(flag, index + 1)
                for index, flag in enumerate(flags)
            ]
            passport = next(
                (document for document in applicant_documents if "passport" in document.document_type.lower()),
                None,
            )
            passport_name = passport.applicant_name if passport and passport.applicant_name else "Unknown applicant"
            if all(document.is_invitee_document for document in applicant_documents):
                passport_name = applicant_documents[0].applicant_name or "Invitee / host"
            comments.append(f"{passport_name}: {len(applicant_documents)} document(s), {len(flags)} finding(s)")
            total_documents += len(applicant_documents)
            total_findings += len(flags)
            for document in applicant_documents:
                document_flags = [
                    flag for flag in numbered_flags
                    if document.document_type in flag or "Passport document" in flag
                ]
                language = "Foreign" if document.is_foreign_language else "English"
                certified = "Certified" if document.has_certified_translation else "No translation"
                self.tree.insert(
                    "", "end",
                    values=(
                        document.source_filename or document.document_type,
                        passport_name,
                        f"{language} / {certified}",
                        self.wrap_findings("\n".join(f"• {finding}" for finding in document_flags) or "OK"),
                    ),
                    tags=(self.finding_tag(document_flags),),
                )

            all_findings.extend((passport_name, f"• {finding}") for finding in numbered_flags)
            for flag in numbered_flags:
                if not any(
                    flag in str(self.tree.item(item_id)["values"][3])
                    for item_id in self.tree.get_children()
                ):
                    self.tree.insert(
                        "", "end",
                        values=("Group check", passport_name, "", self.wrap_findings(flag)),
                        tags=(self.finding_tag([flag]),),
                    )

        self.document_count.configure(text=str(total_documents))
        self.applicant_count.configure(text=str(applicant_group_count))
        self.issue_count.configure(text=str(total_findings))
        self.update_findings_row_height()
        self.status_progress.configure(value=100)
        self.status_var.set(
            f"Scan complete - {total_documents} documents, "
            f"{applicant_group_count} applicants, {total_findings} findings"
        )
        finding_summary = "\n".join(
            f"{applicant}: {finding}" for applicant, finding in all_findings
        )
        scan_comments = (
            "Scan complete.\n\n"
            + "\n".join(comments)
            + ("\n\nFindings:\n" + finding_summary if finding_summary else "\n\nNo findings.")
        )
        self.last_scan_comments = scan_comments
        self.last_scan_findings = all_findings
        self.set_comments(scan_comments)
        self.report_button.configure(state="normal")

    def generate_report(self):
        if not self.folder_path or not self.last_financial_reports:
            self.show_error("Run a scan before generating a PDF report.")
            return

        output_path = Path(self.folder_path) / (
            f"visa_verification_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        self.report_button.configure(state="disabled")
        self.status_var.set("Generating professional PDF report with Gemini...")
        self.set_comments("Generating professional PDF report with Gemini...")

        def create_report_in_background():
            try:
                report_path = generate_pdf_report(
                    output_path,
                    self.jurisdiction_var.get(),
                    self.folder_path,
                    self.last_scan_comments,
                    self.last_scan_findings,
                    self.last_financial_reports,
                )
            except Exception as error:
                self.root.after(0, self.finish_report_error, error)
                return
            self.root.after(0, self.finish_report, report_path)

        threading.Thread(target=create_report_in_background, name="pdf-report", daemon=True).start()

    def finish_report(self, report_path):
        self.report_button.configure(state="normal")
        self.status_var.set(f"PDF report ready: {report_path.name}")
        self.set_comments(f"PDF report created and opened:\n{report_path}")
        os.startfile(str(report_path))

    def finish_report_error(self, error):
        self.report_button.configure(state="normal")
        self.status_var.set("PDF report failed")
        self.set_comments(f"PDF report failed: {error}")

    def update_financial_progress(self, message, completed, total):
        progress_value = (completed / total * 100) if total else 0
        self.status_var.set(message)
        self.set_comments(message)
        self.status_progress.configure(value=progress_value)
        self.root.update_idletasks()

    def clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for item_id in self.financial_report_tree.get_children():
            self.financial_report_tree.delete(item_id)
        ttk.Style(self.root).configure("Treeview", rowheight=48)
        self.document_count.configure(text="0")
        self.applicant_count.configure(text="0")
        self.issue_count.configure(text="0")
        self.last_scan_comments = ""
        self.last_scan_findings = []
        self.last_financial_reports = []
        self.report_button.configure(state="disabled")
        self.set_financial_report_details("No financial report available.")

    def set_comments(self, message):
        self.comments.configure(state="normal")
        self.comments.delete("1.0", "end")
        self.comments.insert("1.0", message)
        self.comments.configure(state="disabled")

    def wrap_findings(self, message):
        return fill(message, width=72, break_long_words=False, subsequent_indent="  ")

    def number_finding(self, finding, number):
        finding = str(finding)
        if finding.startswith("ERROR:"):
            return f"ERROR {number}: {finding[6:].strip()}"
        if finding.startswith("INFO:"):
            return f"INFO {number}: {finding[5:].strip()}"
        return f"ERROR {number}: {finding}"

    def finding_tag(self, findings):
        if any(str(finding).startswith("ERROR") for finding in findings):
            return "error"
        if any(str(finding).startswith("INFO") for finding in findings):
            return "info"
        return "ok"

    def update_findings_row_height(self):
        max_lines = 1
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id).get("values", ())
            finding = str(values[3]) if len(values) > 3 else ""
            max_lines = max(max_lines, finding.count("\n") + 1)
        ttk.Style(self.root).configure("Treeview", rowheight=min(180, max(48, 18 * max_lines + 18)))

    def show_error(self, message):
        self.clear_results()
        self.status_var.set("Scan error")
        self.status_progress.stop()
        self.set_comments(message)
        self.tree.insert("", "end", values=("Scan status", "", "", message), tags=("issue",))

if __name__ == "__main__":
    root = tk.Tk()
    app = VisaAppGUI(root)
    root.mainloop()