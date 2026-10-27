"""PDF de devis / facture généré localement (reportlab), avec les mentions légales françaises usuelles."""

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import BillingDoc, Company
from app.services.billing import vat_breakdown

BRAND = colors.HexColor("#2a55d6")
MUTED = colors.HexColor("#64748b")


def money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " €"


def num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def render_pdf(doc: BillingDoc, company: Company | None, seller: dict[str, str]) -> bytes:
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9, leading=12)
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
        title=f"{'Devis' if doc.kind == 'quote' else 'Facture'} {doc.number or 'brouillon'}",
    )
    title = "DEVIS" if doc.kind == "quote" else "FACTURE"
    number = doc.number or "BROUILLON"

    seller_lines = [
        seller.get("company_name") or "Votre société",
        seller.get("company_legal_form", ""),
        seller.get("company_address", ""),
        f"SIRET : {seller['company_siret']}" if seller.get("company_siret") else "",
        f"TVA : {seller['company_vat']}" if seller.get("company_vat") else "",
        seller.get("company_email", ""),
        seller.get("company_phone", ""),
    ]
    client_lines = [
        company.name if company else "—",
        company.address if company else "",
        f"{company.postal_code} {company.city}".strip() if company else "",
        f"SIRET : {company.siret}" if company and company.siret else "",
        f"TVA : {company.vat_number}" if company and company.vat_number else "",
    ]

    story = [
        Table(
            [
                [
                    _p(title, h1),
                    _p(
                        f"N° {number}\nDate : {doc.issue_date:%d/%m/%Y}"
                        + (
                            f"\n{'Valable jusqu’au' if doc.kind == 'quote' else 'Échéance'} : {doc.due_date:%d/%m/%Y}"
                            if doc.due_date
                            else ""
                        ),
                        right,
                    ),
                ]
            ],
            colWidths=[90 * mm, 84 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        ),
        Spacer(1, 8 * mm),
    ]
    story.append(
        Table(
            [
                [
                    [_p(seller_lines[0], bold)] + [_p(x, base) for x in seller_lines[1:] if x],
                    [_p("Destinataire", small), _p(client_lines[0], bold)]
                    + [_p(x, base) for x in client_lines[1:] if x],
                ]
            ],
            colWidths=[87 * mm, 87 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP")],
        )
    )
    story.append(Spacer(1, 8 * mm))
    if doc.title:
        story += [_p(f"Objet : {doc.title}", bold), Spacer(1, 3 * mm)]

    rows = [["Désignation", "Qté", "PU HT", "TVA", "Total HT"]]
    for ln in doc.lines:
        rows.append(
            [
                _p(ln.description, base),
                num(ln.quantity),
                money(ln.unit_price),
                f"{num(ln.vat_rate)} %",
                money(round(ln.quantity * ln.unit_price, 2)),
            ]
        )
    table = Table(rows, colWidths=[84 * mm, 16 * mm, 26 * mm, 16 * mm, 32 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story += [table, Spacer(1, 5 * mm)]

    tot = [["Total HT", money(doc.total_ht)]]
    tot += [
        [f"TVA {num(rate)} % (base {money(base_ht)})", money(vat)]
        for rate, base_ht, vat in vat_breakdown(doc.lines)
    ]
    tot += [["Total TTC", money(doc.total_ttc)]]
    if doc.kind == "invoice" and doc.amount_paid:
        tot += [
            ["Déjà réglé", money(-doc.amount_paid)],
            ["Reste à payer", money(max(doc.total_ttc - doc.amount_paid, 0))],
        ]
    t2 = Table(tot, colWidths=[60 * mm, 32 * mm], hAlign="RIGHT")
    t2.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                (
                    "FONTNAME",
                    (0, -1 if not doc.amount_paid else -3),
                    (-1, -1 if not doc.amount_paid else -3),
                    "Helvetica-Bold",
                ),
                (
                    "LINEABOVE",
                    (0, -1 if not doc.amount_paid else -3),
                    (-1, -1 if not doc.amount_paid else -3),
                    0.8,
                    BRAND,
                ),
            ]
        )
    )
    story += [t2, Spacer(1, 8 * mm)]

    if doc.notes:
        story += [_p(doc.notes, base), Spacer(1, 4 * mm)]
    if doc.kind == "invoice":
        pay = ["Règlement par virement bancaire."]
        if seller.get("company_iban"):
            pay.append(
                f"IBAN : {seller['company_iban']}"
                + (f" – BIC : {seller['company_bic']}" if seller.get("company_bic") else "")
            )
        pay.append(
            "En cas de retard de paiement : pénalités égales à 3 fois le taux d’intérêt légal et indemnité forfaitaire "
            "de recouvrement de 40 € (art. L441-10 du Code de commerce). Pas d’escompte pour paiement anticipé."
        )
        story += [_p("\n".join(pay), small)]
    else:
        story += [
            _p(
                "Devis valable jusqu’à la date indiquée. Bon pour accord : date, signature et mention « Bon pour accord ».",
                small,
            )
        ]
    if seller.get("invoice_legal_notes"):
        story += [Spacer(1, 2 * mm), _p(seller["invoice_legal_notes"], small)]
    if doc.status == "draft":
        story += [
            Spacer(1, 4 * mm),
            _p(
                "BROUILLON – document non émis, sans valeur légale.",
                ParagraphStyle("w", parent=bold, textColor=colors.red),
            ),
        ]

    pdf.build(story)
    return buf.getvalue()
