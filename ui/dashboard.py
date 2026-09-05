import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path
from textwrap import fill

from core.rules import run_cross_validation_rules
from core.scanner import scan_folder

class VisaAppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Visa Document Verifier")
        self.root.geometry("1180x720")
        self.root.minsize(900, 600)
        self.root.state("zoomed")
        self.folder_path = None
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
        ttk.Button(control_frame, text="Run scan", command=self.run_audit, style="Accent.TButton").pack(
            side="left", padx=(12, 0)
        )
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

        body = ttk.Panedwindow(root, orient="vertical")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 10))

        documents_frame = ttk.LabelFrame(body, text="Documents found", padding=10)
        comments_frame = ttk.LabelFrame(body, text="Scan comments", padding=10)
        body.add(documents_frame, weight=1)
        body.add(comments_frame, weight=1)

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
        self.progress = ttk.Progressbar(comments_frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(10, 0))

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
        self.progress.configure(value=0)
        self.status_var.set("Scanning documents...")
        self.status_progress.configure(value=0)

        def report_progress(message, completed, total):
            self.set_comments(message)
            self.status_var.set(message)
            progress_value = (completed / total * 100) if total else 0
            self.progress.configure(value=progress_value)
            self.status_progress.configure(value=progress_value)
            self.root.update_idletasks()

        try:
            grouped_documents = scan_folder(
                self.folder_path,
                self.jurisdiction_var.get(),
                progress_callback=report_progress,
            )
        except Exception as error:
            self.status_var.set("Scan failed")
            self.show_error(f"Scan failed: {error}")
            return

        if not grouped_documents:
            self.status_var.set("Scan finished - no documents found")
            self.show_error("No supported documents found in the selected folder.")
            return

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
        self.progress.configure(value=100)
        self.status_progress.configure(value=100)
        self.status_var.set(
            f"Scan complete - {total_documents} documents, "
            f"{applicant_group_count} applicants, {total_findings} findings"
        )
        finding_summary = "\n".join(
            f"{applicant}: {finding}" for applicant, finding in all_findings
        )
        self.set_comments(
            "Scan complete.\n\n"
            + "\n".join(comments)
            + ("\n\nFindings:\n" + finding_summary if finding_summary else "\n\nNo findings.")
        )

    def clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        ttk.Style(self.root).configure("Treeview", rowheight=48)
        self.document_count.configure(text="0")
        self.applicant_count.configure(text="0")
        self.issue_count.configure(text="0")

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
        self.progress.stop()
        self.set_comments(message)
        self.tree.insert("", "end", values=("Scan status", "", "", message), tags=("issue",))

if __name__ == "__main__":
    root = tk.Tk()
    app = VisaAppGUI(root)
    root.mainloop()