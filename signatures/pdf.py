import io
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from signatures.qr import generate_qr_image


def _get_university_logo():
    """Finds university logo from static directory."""
    dark = settings.BASE_DIR / 'static' / 'images' / 'logo-dark.png'
    light = settings.BASE_DIR / 'static' / 'images' / 'logo-light.png'
    if dark.exists():
        return dark
    if light.exists():
        return light
    return None


def _get_pdf_styles():
    """Defines typographic styles for the official signed PDF document."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        'UnivHeaderTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=19,
        textColor=colors.HexColor('#0f172a'),
        alignment=1,  # Center
    ))
    styles.add(ParagraphStyle(
        'UnivHeaderSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569'),
        alignment=1,  # Center
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        'DocMainTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#1e40af'),  # Deep Navy Blue
        alignment=1,  # Center
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        'DocMetaBadge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#0f172a'),
    ))
    styles.add(ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor('#1e3a8a'),
        spaceBefore=8,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        'CellLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#334155'),
    ))
    styles.add(ParagraphStyle(
        'CellValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#0f172a'),
    ))
    styles.add(ParagraphStyle(
        'BodyTextDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#1e293b'),
    ))
    styles.add(ParagraphStyle(
        'SigLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#1e3a8a'),
    ))
    styles.add(ParagraphStyle(
        'SigValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#0f172a'),
    ))
    styles.add(ParagraphStyle(
        'SigHash',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor('#475569'),
    ))
    styles.add(ParagraphStyle(
        'QrCaption',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=9,
        textColor=colors.HexColor('#475569'),
        alignment=1,  # Center
    ))
    return styles


def generate_signed_task_pdf(signature, request=None) -> io.BytesIO:
    """
    Generates an official, legal-grade task execution & completion certificate PDF in English.
    Contains:
      - Top University Logo & University Name ('AL-KHWARIZMI UNIVERSITY')
      - Document Title & Verification ID
      - Complete Task Information (Title, number, department, assignees, deadlines)
      - Execution Processes (Submission details, Department Head approval remarks, work notes)
      - Cryptographic Electronic Signature block with embedded real QR Code
      - Official Rector institutional validation and legal authority disclaimer
    """
    from django.utils.translation import override

    with override('en'):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=32,
            bottomMargin=32,
        )
        styles = _get_pdf_styles()
        story = []

        task = signature.task
        signer = signature.signer

        # Build verification URL
        verification_url = f"http://127.0.0.1:8000/verify/{signature.verification_id}/"
        if request:
            try:
                verification_url = request.build_absolute_uri(
                    reverse('public_verify', kwargs={'verification_id': signature.verification_id})
                )
            except Exception:
                pass

        # -----------------------------------------------------------------------
        # 1. TOP HEADER: UNIVERSITY LOGO & UNIVERSITY NAME
        # -----------------------------------------------------------------------
        logo_path = _get_university_logo()
        univ_title_en = "AL-KHWARIZMI UNIVERSITY"
        univ_sub_en = "AL-KHWARIZMI UNIVERSITY &bull; CENTRAL RECTORATE &bull; OFFICIAL DOCUMENT"

        if logo_path and logo_path.exists():
            try:
                from PIL import Image as PILImage
                with PILImage.open(str(logo_path)) as pil_img:
                    orig_w, orig_h = pil_img.size
                aspect = (orig_w / orig_h) if orig_h else 1.0
                target_h = 0.72 * inch
                target_w = target_h * aspect

                logo_img = Image(str(logo_path), width=target_w, height=target_h)
                title_block = [
                    Paragraph(f"<b>{univ_title_en}</b>", styles['UnivHeaderTitle']),
                    Paragraph(univ_sub_en, styles['UnivHeaderSub']),
                ]
                col_logo = target_w + 0.15 * inch
                col_title = max(2.0 * inch, 7.1 * inch - col_logo)
                header_table = Table([[logo_img, title_block]], colWidths=[col_logo, col_title])
                header_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                    ('ALIGN', (1, 0), (1, 0), 'CENTER'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ]))
                story.append(header_table)
            except Exception:
                story.append(Paragraph(f"<b>{univ_title_en}</b>", styles['UnivHeaderTitle']))
                story.append(Paragraph(univ_sub_en, styles['UnivHeaderSub']))
        else:
            story.append(Paragraph(f"<b>{univ_title_en}</b>", styles['UnivHeaderTitle']))
            story.append(Paragraph(univ_sub_en, styles['UnivHeaderSub']))

        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1e40af'), spaceAfter=8))

        # Document Title
        story.append(Paragraph(
            "<b>OFFICIAL ELECTRONICALLY SIGNED TASK EXECUTION ACT</b><br/>"
            "<font size=8 color='#64748b'>CENTRAL RECTORATE &bull; DIGITAL VERIFICATION CERTIFICATE</font>",
            styles['DocMainTitle']
        ))

        # Reference Strip Table
        signed_date_str = signature.signed_at.strftime("%d.%m.%Y %H:%M")
        ref_table_data = [
            [
                Paragraph(f"<b>Task No.:</b> {task.task_number}", styles['DocMetaBadge']),
                Paragraph(f"<b>Verification ID:</b> <font color='#1e40af'>{signature.verification_id}</font>", styles['DocMetaBadge']),
                Paragraph(f"<b>Date:</b> {signed_date_str}", styles['DocMetaBadge']),
            ]
        ]
        ref_table = Table(ref_table_data, colWidths=[2.3 * inch, 2.7 * inch, 2.1 * inch])
        ref_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(ref_table)
        story.append(Spacer(1, 10))

        # -----------------------------------------------------------------------
        # 2. SECTION 1: GENERAL TASK INFORMATION
        # -----------------------------------------------------------------------
        story.append(Paragraph("1. GENERAL TASK INFORMATION", styles['SectionHeading']))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cbd5e1'), spaceAfter=4))

        # Prepare assignee display string
        assignees_list = []
        for a in task.assignments.all().select_related('user', 'user__position'):
            pos = f" ({a.user.position.name})" if a.user.position else ""
            assignees_list.append(f"{a.user.display_name}{pos}")
        assignees_text = ", ".join(assignees_list) if assignees_list else "—"

        dept_name = task.responsible_department.name if task.responsible_department else "—"
        creator_name = task.creator.display_name if task.creator else "—"
        deadline_str = task.deadline.strftime("%d.%m.%Y") if task.deadline else "—"
        completed_str = task.completed_at.strftime("%d.%m.%Y %H:%M") if task.completed_at else signed_date_str

        task_info_matrix = [
            [
                Paragraph("Task Title:", styles['CellLabel']),
                Paragraph(f"<b>{task.title}</b>", styles['CellValue']),
                Paragraph("Responsible Department:", styles['CellLabel']),
                Paragraph(dept_name, styles['CellValue']),
            ],
            [
                Paragraph("Created / Assigned by:", styles['CellLabel']),
                Paragraph(creator_name, styles['CellValue']),
                Paragraph("Assigned Employee(s):", styles['CellLabel']),
                Paragraph(assignees_text, styles['CellValue']),
            ],
            [
                Paragraph("Priority Level:", styles['CellLabel']),
                Paragraph(task.get_priority_display(), styles['CellValue']),
                Paragraph("Complexity Level:", styles['CellLabel']),
                Paragraph(task.get_complexity_display(), styles['CellValue']),
            ],
            [
                Paragraph("Deadline:", styles['CellLabel']),
                Paragraph(deadline_str, styles['CellValue']),
                Paragraph("Completed Date:", styles['CellLabel']),
                Paragraph(completed_str, styles['CellValue']),
            ],
        ]

        task_table = Table(task_info_matrix, colWidths=[1.5 * inch, 2.1 * inch, 1.5 * inch, 2.0 * inch])
        task_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(task_table)

        # Task Description
        if task.description:
            story.append(Spacer(1, 4))
            desc_table = Table([
                [Paragraph("Task Description & Objectives:", styles['CellLabel'])],
                [Paragraph(task.description.replace('\n', '<br/>'), styles['BodyTextDark'])],
            ], colWidths=[7.1 * inch])
            desc_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#ffffff')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(desc_table)

        story.append(Spacer(1, 8))

        # -----------------------------------------------------------------------
        # 3. SECTION 2: TASK EXECUTION & APPROVAL WORKFLOW
        # -----------------------------------------------------------------------
        story.append(Paragraph("2. TASK EXECUTION & APPROVAL WORKFLOW", styles['SectionHeading']))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cbd5e1'), spaceAfter=4))

        # A. Latest Employee Submission
        latest_submission = task.submissions.order_by('-version').first()
        if latest_submission:
            sub_time_str = latest_submission.submitted_at.strftime("%d.%m.%Y %H:%M") if latest_submission.submitted_at else "—"
            sub_by_str = latest_submission.submitted_by.display_name if latest_submission.submitted_by else "Employee"
            sub_rows = [
                [
                    Paragraph(f"<b>Employee Submission (v{latest_submission.version}):</b> {sub_by_str} &bull; Submitted: {sub_time_str}", styles['CellLabel'])
                ],
                [
                    Paragraph(
                        (latest_submission.submission_text or "No submission report text provided.").replace('\n', '<br/>'),
                        styles['BodyTextDark']
                    )
                ]
            ]
            sub_table = Table(sub_rows, colWidths=[7.1 * inch])
            sub_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0f2fe')),  # Sky light
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#ffffff')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#7dd3fc')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(sub_table)
            story.append(Spacer(1, 4))

        # B. Department Head First Approval Review
        first_approval = task.approvals.filter(
            stage='FIRST_APPROVAL',
            decision='APPROVED',
        ).order_by('-created_at').first()

        if first_approval:
            appr_time_str = first_approval.created_at.strftime("%d.%m.%Y %H:%M")
            appr_by_str = first_approval.actor.display_name if first_approval.actor else "Department Head"
            appr_notes = first_approval.reason.strip() if first_approval.reason else "Approved and submitted to the Rectorate for final electronic signature."
            appr_rows = [
                [
                    Paragraph(f"<b>Department Head Review & Approval:</b> {appr_by_str} &bull; {appr_time_str}", styles['CellLabel'])
                ],
                [
                    Paragraph(f"<b>Decision:</b> <font color='#15803d'>APPROVED (First Stage)</font><br/><b>Review Remarks / Notes:</b> {appr_notes}", styles['BodyTextDark'])
                ]
            ]
            appr_table = Table(appr_rows, colWidths=[7.1 * inch])
            appr_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dcfce7')),  # Green light
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#ffffff')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#86efac')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(appr_table)
            story.append(Spacer(1, 4))

        # C. Work Notes (Up to 3 latest work notes)
        work_notes = task.notes.order_by('-created_at')[:3]
        if work_notes.exists():
            notes_lines = []
            for wn in work_notes:
                notes_lines.append(
                    f"&bull; <b>{wn.author.display_name}</b> ({wn.created_at.strftime('%d.%m %H:%M')}): {wn.content}"
                )
            notes_content = "<br/>".join(notes_lines)
            notes_table = Table([
                [Paragraph("Work Notes & Progress Monitoring:", styles['CellLabel'])],
                [Paragraph(notes_content, styles['BodyTextDark'])],
            ], colWidths=[7.1 * inch])
            notes_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#ffffff')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(notes_table)
            story.append(Spacer(1, 4))

        # D. Attached Evidence Files and Reports Summary
        files_count = task.files.filter(is_active=True).count()
        reports_count = task.reports.filter(status='APPROVED').count()
        if files_count > 0 or reports_count > 0:
            file_summary_text = f"A total of <b>{files_count}</b> verified digital attachment(s) and <b>{reports_count}</b> approved official report(s) are attached to this task record with SHA-256 integrity validation."
            story.append(Paragraph(file_summary_text, styles['BodyTextDark']))
            story.append(Spacer(1, 4))

        story.append(Spacer(1, 6))

        # -----------------------------------------------------------------------
        # 4. SECTION 3: OFFICIAL ELECTRONIC SIGNATURE BOX & QR CODE
        # -----------------------------------------------------------------------
        signer_pos = signer.position.name if (hasattr(signer, 'position') and signer.position) else "Rector of the University"
        sig_details = [
            [
                Paragraph("OFFICIAL UNIVERSITY ELECTRONIC SIGNATURE & VALIDATION SEAL", styles['SigLabel']),
                Paragraph("", styles['SigLabel']),
            ],
            [
                # Left Sub-block: Signer attributes
                Table([
                    [Paragraph("Signer (Authority):", styles['SigLabel']), Paragraph(f"<b>{signer.display_name}</b>", styles['SigValue'])],
                    [Paragraph("Position:", styles['SigLabel']), Paragraph(signer_pos, styles['SigValue'])],
                    [Paragraph("Institution:", styles['SigLabel']), Paragraph("Al-Khwarizmi University — Office of the Rector", styles['SigValue'])],
                    [Paragraph("Signature Status:", styles['SigLabel']), Paragraph("<font color='#15803d'><b>VALID & OFFICIALLY VERIFIED</b></font>", styles['SigValue'])],
                    [Paragraph("Signed Timestamp:", styles['SigLabel']), Paragraph(signed_date_str, styles['SigValue'])],
                    [Paragraph("Verification ID:", styles['SigLabel']), Paragraph(f"<b>{signature.verification_id}</b>", styles['SigValue'])],
                    [Paragraph("Cryptographic Algorithm:", styles['SigLabel']), Paragraph(f"{signature.algorithm} ({signature.key_version})", styles['SigValue'])],
                    [Paragraph("SHA-256 Hash:", styles['SigLabel']), Paragraph(signature.payload_hash[:48] + "...", styles['SigHash'])],
                ], colWidths=[1.6 * inch, 3.7 * inch]),

                # Right Sub-block: Embedded QR Code
                Table([
                    [Image(generate_qr_image(verification_url, box_size=6, border=1), width=1.35 * inch, height=1.35 * inch)],
                    [Paragraph("<b>Scan QR Code</b><br/>Verify Authenticity", styles['QrCaption'])],
                ], colWidths=[1.6 * inch])
            ]
        ]

        sig_main_table = Table(sig_details, colWidths=[5.4 * inch, 1.7 * inch])
        sig_main_table.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f8fafc')),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#1e40af')),
            ('LINEBELOW', (0, 0), (-1, 0), 1.0, colors.HexColor('#1e40af')),
            ('TOPPADDING', (0, 0), (-1, 0), 5),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, 1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, 1), 6),
            ('VALIGN', (0, 1), (-1, 1), 'MIDDLE'),
            ('ALIGN', (1, 1), (1, 1), 'CENTER'),
        ]))

        # Institutional Rector legal authority disclaimer in English
        rector_disclaimer_text = (
            "This document has been electronically signed and officially validated by the Rector "
            "of Al-Khwarizmi University and holds full institutional and legal authority at the "
            "university level. To verify the authenticity and validity of this document, "
            "scan the QR code above or access the public verification portal."
        )

        # Keep the entire signature block together to avoid awkward page breaks
        story.append(KeepTogether([
            sig_main_table,
            Spacer(1, 4),
            Paragraph(
                f"<font size=7 color='#475569'><i>{rector_disclaimer_text}</i></font>",
                styles['QrCaption']
            )
        ]))

        doc.build(story)
        buffer.seek(0)
        return buffer
