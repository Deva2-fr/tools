"""PDF de note de frais généré localement (reportlab), sans modèle Google Doc."""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Expense
from app.services.billing_pdf import BRAND, MUTED, _p, money, num


def number(e: Expense) -> str:
    return f"NDF-{e.expense_date:%Y%m}-{e.id:04d}"


def filename(e: Expense) -> str:
    return f"{number(e)}.pdf"


def render_pdf(e: Expense, company: dict[str, str]) -> bytes:
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=base, fontSize=8, textColor=MUTED, leading=10)
    h1 = ParagraphStyle(
        "h1", parent=base, fontName="Helvetica-Bold", fontSize=20, textColor=BRAND, leading=24
    )
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    right = ParagraphStyle("right", parent=base, alignment=2)

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"Note de frais {number(e)}",
    )
    seller = [
        company.get("company_name") or "Votre société",
        company.get("company_address", ""),
        f"SIRET : {company['company_siret']}" if company.get("company_siret") else "",
    ]
    story = [
        Table(
            [
                [
                    _p("NOTE DE FRAIS", h1),
                    _p(f"N° {number(e)}\nÉtablie le {date.today():%d/%m/%Y}", right),
                ]
            ],
            colWidths=[100 * mm, 74 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        ),
        Spacer(1, 6 * mm),
        _p(seller[0], bold),
        *[_p(x, base) for x in seller[1:] if x],
        Spacer(1, 8 * mm),
    ]

    info = [
        ("Collaborateur", e.employee),
        ("Date de la dépense", f"{e.expense_date:%d/%m/%Y}"),
        ("Motif", e.reason),
        ("Catégorie", e.category),
        ("Projet / client", e.project),
        ("Moyen de paiement", e.payment_method),
    ]
    t = Table(
        [[_p(k, small), _p(v or "—", base)] for k, v in info],
        colWidths=[48 * mm, 126 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [t, Spacer(1, 8 * mm)]

    amounts = Table(
        [
            ["Montant HT", money(e.amount_ht)],
            [f"TVA ({num(e.vat_rate)} %)", money(e.amount_vat)],
            ["Total TTC à rembourser", money(e.amount_ttc)],
        ],
        colWidths=[60 * mm, 40 * mm],
        hAlign="RIGHT",
    )
    amounts.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2ff")),
                ("LINEABOVE", (0, -1), (-1, -1), 0.6, BRAND),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [amounts, Spacer(1, 8 * mm)]
    if e.notes:
        story += [_p("Notes", small), _p(e.notes, base), Spacer(1, 8 * mm)]

    story.append(
        Table(
            [
                [_p("Signature du collaborateur", small), _p("Visa de la direction", small)],
                ["", ""],
            ],
            colWidths=[87 * mm, 87 * mm],
            rowHeights=[None, 22 * mm],
            style=[("BOX", (0, 1), (0, 1), 0.4, MUTED), ("BOX", (1, 1), (1, 1), 0.4, MUTED)],
        )
    )
    story += [Spacer(1, 4 * mm), _p("Justificatifs à joindre à la présente note.", small)]
    pdf.build(story)
    return buf.getvalue()
