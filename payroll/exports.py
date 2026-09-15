import io
from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext as _
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm, mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

from payroll.models import PayrollPeriod, PayrollRecord


def generate_payslip_pdf(record: PayrollRecord) -> bytes:
    """Generates an official, institutional university payslip PDF for an employee in English."""
    from django.utils.translation import override

    with override('en'):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=1.5 * cm,
            leftMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#1e3a8a'),
            alignment=1,  # Center
        )
        subtitle_style = ParagraphStyle(
            'DocSubTitle',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor('#475569'),
            alignment=1,
        )
        section_style = ParagraphStyle(
            'SectionHeading',
            parent=styles['Heading2'],
            fontSize=12,
            leading=16,
            textColor=colors.HexColor('#0f172a'),
            spaceBefore=8,
            spaceAfter=4,
        )
        cell_bold = ParagraphStyle('CellBold', parent=styles['Normal'], fontSize=9, leading=11, fontName='Helvetica-Bold')
        cell_normal = ParagraphStyle('CellNormal', parent=styles['Normal'], fontSize=9, leading=11)
        cell_right = ParagraphStyle('CellRight', parent=styles['Normal'], fontSize=9, leading=11, alignment=2)

        story = []

        # University Header
        story.append(Paragraph("<b>AL-KHWARIZMI UNIVERSITY</b>", title_style))
        story.append(Paragraph("OFFICIAL PAYSLIP &amp; SALARY STATEMENT", subtitle_style))
        story.append(Spacer(1, 0.4 * cm))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1e3a8a'), spaceAfter=15))

        # Metadata Grid
        meta_data = [
            [
                Paragraph(f"<b>{_('Employee Name')}:</b>", cell_normal),
                Paragraph(record.employee_name_snapshot, cell_bold),
                Paragraph(f"<b>{_('Payroll Period')}:</b>", cell_normal),
                Paragraph(f"{record.period.name} ({record.period.code})", cell_bold),
            ],
            [
                Paragraph(f"<b>{_('Department')}:</b>", cell_normal),
                Paragraph(record.department_snapshot or _('Not assigned'), cell_normal),
                Paragraph(f"<b>{_('Payment Status')}:</b>", cell_normal),
                Paragraph(record.get_payment_status_display(), cell_bold),
            ],
            [
                Paragraph(f"<b>{_('Position')}:</b>", cell_normal),
                Paragraph(record.position_snapshot or _('Not assigned'), cell_normal),
                Paragraph(f"<b>{_('Disbursed Date')}:</b>", cell_normal),
                Paragraph(str(record.paid_at.date()) if record.paid_at else '-', cell_normal),
            ],
            [
                Paragraph(f"<b>{_('Grade / Level')}:</b>", cell_normal),
                Paragraph(record.grade_snapshot or _('Standard'), cell_normal),
                Paragraph(f"<b>{_('Reference / Memo')}:</b>", cell_normal),
                Paragraph(record.payment_reference or '-', cell_normal),
            ],
        ]

        meta_table = Table(meta_data, colWidths=[3.2 * cm, 5.5 * cm, 3.5 * cm, 5.8 * cm])
        meta_table.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
                ('PADDING', (0, 0), (-1, -1), 5),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ])
        )
        story.append(meta_table)
        story.append(Spacer(1, 0.5 * cm))

        # Itemized Breakdown Table
        story.append(Paragraph(_('Compensation & Earnings Breakdown'), section_style))

        lines = record.lines.all().order_by('component_type', 'name_snapshot')
        table_data = [
            [
                Paragraph(f"<b>{_('Item / Description')}</b>", cell_bold),
                Paragraph(f"<b>{_('Category')}</b>", cell_bold),
                Paragraph(f"<b>{_('Basis / Rate')}</b>", cell_bold),
                Paragraph(f"<b>{_('Amount (UZS)')}</b>", cell_right),
            ]
        ]

        for line in lines:
            rate_repr = f"{line.rate_or_value:,.2f}" if line.rate_or_value else "-"
            table_data.append([
                Paragraph(line.name_snapshot, cell_normal),
                Paragraph(line.get_component_type_display(), cell_normal),
                Paragraph(rate_repr, cell_normal),
                Paragraph(f"{line.amount:,.2f}", cell_right),
            ])

        breakdown_table = Table(table_data, colWidths=[7.0 * cm, 3.5 * cm, 3.5 * cm, 4.0 * cm])
        breakdown_table.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('PADDING', (0, 0), (-1, -1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ])
        )
        story.append(breakdown_table)
        story.append(Spacer(1, 0.5 * cm))

        # Summary Totals Box
        summary_data = [
            [Paragraph(f"<b>{_('Base Salary')}:</b>", cell_normal), Paragraph(f"{record.base_salary:,.2f} UZS", cell_right)],
            [Paragraph(f"<b>{_('Total Allowances')}:</b>", cell_normal), Paragraph(f"{record.total_allowances:,.2f} UZS", cell_right)],
            [Paragraph(f"<b>{_('Total Bonuses & Incentives')}:</b>", cell_normal), Paragraph(f"{record.total_bonuses:,.2f} UZS", cell_right)],
            [Paragraph(f"<b>{_('KPI Performance Bonus')}:</b>", cell_normal), Paragraph(f"{record.kpi_bonus:,.2f} UZS", cell_right)],
            [Paragraph(f"<b>{_('Gross Salary')}:</b>", cell_bold), Paragraph(f"<b>{record.gross_salary:,.2f} UZS</b>", cell_right)],
            [Paragraph(f"<b>{_('Total Deductions')}:</b>", cell_normal), Paragraph(f"- {record.total_deductions:,.2f} UZS", cell_right)],
            [Paragraph(f"<b>{_('Total Taxes Deducted')}:</b>", cell_normal), Paragraph(f"- {record.tax_total:,.2f} UZS", cell_right)],
            [Paragraph(f"<b>{_('NET SALARY PAYABLE')}:</b>", ParagraphStyle('NetTitle', parent=cell_bold, fontSize=11, textColor=colors.HexColor('#166534'))),
             Paragraph(f"<b>{record.net_salary:,.2f} {record.currency}</b>", ParagraphStyle('NetAmt', parent=cell_right, fontSize=12, fontName='Helvetica-Bold', textColor=colors.HexColor('#166534')))],
        ]

        summary_table = Table(summary_data, colWidths=[9.0 * cm, 9.0 * cm])
        summary_table.setStyle(
            TableStyle([
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dcfce7')),
                ('PADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 3), (-1, 3), 1, colors.HexColor('#cbd5e1')),
                ('LINEBELOW', (0, 6), (-1, 6), 1, colors.HexColor('#cbd5e1')),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#94a3b8')),
            ])
        )
        story.append(summary_table)
        story.append(Spacer(1, 1.0 * cm))

        # Signatures / Institutional Footer
        sig_data = [
            [
                Paragraph(f"<b>{_('Authorized by')}:</b><br/>{record.approved_by.display_name if record.approved_by else _('University Financial Authority')}<br/><br/>________________________", cell_normal),
                Paragraph(f"<b>{_('Employee Acknowledgment')}:</b><br/>{record.employee_name_snapshot}<br/><br/>________________________", cell_normal),
            ]
        ]
        sig_table = Table(sig_data, colWidths=[9.0 * cm, 9.0 * cm])
        sig_table.setStyle(TableStyle([('PADDING', (0, 0), (-1, -1), 0)]))
        story.append(sig_table)

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()


def generate_period_payroll_excel(period: PayrollPeriod, records_qs=None) -> bytes:
    """Generates a styled Excel (.xlsx) workbook summarizing all payroll records for a period."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{period.code} Payroll"

    # Header styling
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Segoe UI", size=10, bold=True)
    normal_font = Font(name="Segoe UI", size=10)
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='E2E8F0'),
    )

    # Title Block
    ws.merge_cells('A1:L1')
    ws['A1'] = f"TASK MANAGEMENT UNIVERSITY — PAYROLL SUMMARY ({period.name} [{period.code}])"
    ws['A1'].font = Font(name="Segoe UI", size=14, bold=True, color="1E3A8A")
    ws['A1'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells('A2:L2')
    ws['A2'] = f"Generated on {timezone.now().strftime('%Y-%m-%d %H:%M')} | Status: {period.get_status_display()}"
    ws['A2'].font = Font(name="Segoe UI", size=10, italic=True, color="64748B")
    ws['A2'].alignment = Alignment(horizontal="center", vertical="center")

    headers = [
        _("No."),
        _("Employee"),
        _("Department"),
        _("Position"),
        _("Grade"),
        _("Base Salary"),
        _("Allowances"),
        _("Bonuses"),
        _("KPI Bonus"),
        _("Gross Salary"),
        _("Taxes"),
        _("Deductions"),
        _("Net Salary"),
        _("Status"),
        _("Payment"),
    ]

    ws.row_dimensions[4].height = 24
    for col_num, header_title in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_num)
        cell.value = str(header_title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    if records_qs is None:
        records_qs = period.records.all().select_related('employee', 'period', 'approved_by')

    row_num = 5
    for idx, rec in enumerate(records_qs, 1):
        ws.row_dimensions[row_num].height = 20
        row_data = [
            idx,
            rec.employee_name_snapshot,
            rec.department_snapshot or "-",
            rec.position_snapshot or "-",
            rec.grade_snapshot or "-",
            float(rec.base_salary),
            float(rec.total_allowances),
            float(rec.total_bonuses),
            float(rec.kpi_bonus),
            float(rec.gross_salary),
            float(rec.tax_total),
            float(rec.total_deductions),
            float(rec.net_salary),
            rec.get_status_display(),
            rec.get_payment_status_display(),
        ]
        for col_num, val in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_num, value=val)
            cell.font = normal_font
            cell.border = thin_border
            if col_num in [6, 7, 8, 9, 10, 11, 12, 13]:
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_num in [1, 14, 15]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

        row_num += 1

    # Totals Row
    ws.row_dimensions[row_num].height = 22
    ws.cell(row=row_num, column=2, value=_("TOTALS")).font = bold_font
    for col_idx in range(6, 14):
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        cell = ws.cell(row=row_num, column=col_idx)
        cell.value = f"=SUM({col_letter}5:{col_letter}{row_num-1})"
        cell.font = bold_font
        cell.number_format = '#,##0.00'
        cell.border = thin_border
        cell.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    # Column widths auto-adjustment
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
