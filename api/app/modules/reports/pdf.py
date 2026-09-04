"""Renderização do laudo em PDF (reportlab).

Só texto e tabelas — nada de ggplot/matplotlib.

Sobre o hash impresso no rodapé: um PDF **não pode conter o próprio sha256**.
Imprimir o hash muda os bytes, que mudam o hash — é circular. O que se imprime
(e o que o QR Code carrega) é o **sha256 do snapshot de conteúdo**, que é
estável e existe antes da renderização. O sha256 do ARQUIVO fica em
`reports.sha256`. O endpoint /verify aceita os dois: quem tem o papel na mão
digita o hash impresso; quem tem o arquivo calcula o hash do arquivo. Os dois
provam a mesma coisa.
"""
from io import BytesIO

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_STYLES = getSampleStyleSheet()
_H1 = ParagraphStyle("h1", parent=_STYLES["Heading1"], fontSize=16, spaceAfter=4)
_H2 = ParagraphStyle("h2", parent=_STYLES["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
_BODY = ParagraphStyle("body", parent=_STYLES["BodyText"], fontSize=9, leading=12)
_SMALL = ParagraphStyle("small", parent=_STYLES["BodyText"], fontSize=7, leading=9,
                        textColor=colors.HexColor("#555555"))
_MONO = ParagraphStyle("mono", parent=_SMALL, fontName="Courier", fontSize=6.5)
_CENTER = ParagraphStyle("center", parent=_SMALL, alignment=TA_CENTER)

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
)


def _txt(value) -> str:
    """Célula vazia vira '—'. Nunca 'None' impresso num laudo."""
    if value is None or value == "":
        return "—"
    return str(value)


def _kv_table(pairs: list[tuple[str, object]]) -> Table:
    rows = [[Paragraph(f"<b>{k}</b>", _BODY), Paragraph(_txt(v), _BODY)] for k, v in pairs]
    t = Table(rows, colWidths=[45 * mm, 120 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef1f5")),
            ]
        )
    )
    return t


def _qr_flowable(verify_url: str, size_mm: float = 28) -> Image:
    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=size_mm * mm, height=size_mm * mm)


def _result_value(r: dict) -> str:
    """Abaixo do LOD imprime '<LOD' — nunca o número bruto, nunca zero.

    Um '0,00' onde o método só sabe dizer '<0,05' é uma afirmação que o
    laboratório não pode sustentar.
    """
    if r.get("below_lod"):
        lod = r.get("lod")
        return f"<{lod}" if lod is not None else "<LOD"
    if r.get("display_value"):
        return str(r["display_value"])
    if r.get("value_numeric") is not None:
        return str(r["value_numeric"])
    return _txt(r.get("value_text"))


def build_report_pdf(content: dict, code: str, version: int, verify_url: str) -> bytes:
    org = content.get("organization") or {}
    project = content.get("project") or {}
    customer = content.get("customer") or {}
    samples = content.get("samples") or []
    results = content.get("results") or []
    signer = content.get("signed_by_name") or content.get("tech_responsible") or "—"
    signed_at = content.get("signed_at") or "—"
    content_sha = content.get("content_sha256") or "—"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=f"{code} v{version}",
        author=org.get("name") or "Rizoma",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    story: list = []

    # ── Cabeçalho ───────────────────────────────────────────────────────
    story.append(Paragraph(_txt(org.get("name")), _H1))
    if org.get("cnpj"):
        story.append(Paragraph(f"CNPJ: {org['cnpj']}", _SMALL))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(_txt(content.get("title")) or "Laudo Analítico", _H2))
    story.append(
        _kv_table(
            [
                ("Laudo nº", code),
                ("Versão", version),
                ("Emitido em", content.get("generated_at")),
            ]
        )
    )

    # ── Projeto e cliente ───────────────────────────────────────────────
    story.append(Paragraph("Projeto", _H2))
    story.append(
        _kv_table(
            [
                ("Código", project.get("code")),
                ("Nome", project.get("name")),
                ("Descrição", project.get("description")),
            ]
        )
    )

    story.append(Paragraph("Pesquisador", _H2))
    story.append(
        _kv_table(
            [
                ("Nome", customer.get("name")),
                ("Contato", customer.get("contact_email")),
            ]
        )
    )

    # ── Amostras ────────────────────────────────────────────────────────
    story.append(Paragraph("Amostras", _H2))
    if samples:
        data = [["Código", "Matriz", "Grupo", "Rep.", "Status", "Coleta"]]
        for s in samples:
            data.append(
                [
                    _txt(s.get("code")),
                    _txt(s.get("matrix")),
                    _txt(s.get("treatment_group")),
                    _txt(s.get("replicate")),
                    _txt(s.get("status")),
                    _txt(s.get("occurred_at")),
                ]
            )
        t = Table(data, colWidths=[30 * mm, 28 * mm, 30 * mm, 14 * mm, 25 * mm, 38 * mm])
        t.setStyle(_TABLE_STYLE)
        story.append(t)
    else:
        story.append(Paragraph("Nenhuma amostra vinculada.", _BODY))

    # ── Resultados laboratoriais ────────────────────────────────────────
    story.append(Paragraph("Resultados laboratoriais (aprovados)", _H2))
    if results:
        data = [["Amostra", "Analito", "Valor", "Unidade", "LOD", "LOQ", "Incerteza"]]
        for r in results:
            data.append(
                [
                    _txt(r.get("sample_code")),
                    _txt(r.get("analyte")),
                    _result_value(r),
                    _txt(r.get("unit")),
                    _txt(r.get("lod")),
                    _txt(r.get("loq")),
                    _txt(r.get("uncertainty")),
                ]
            )
        t = Table(
            data,
            colWidths=[26 * mm, 34 * mm, 24 * mm, 22 * mm, 20 * mm, 20 * mm, 22 * mm],
            repeatRows=1,
        )
        t.setStyle(_TABLE_STYLE)
        story.append(t)
        story.append(Spacer(1, 2 * mm))
        story.append(
            Paragraph(
                "Valores precedidos de “&lt;” indicam resultado abaixo do limite de "
                "detecção (LOD) do método. Não equivalem a ausência do analito nem a zero.",
                _SMALL,
            )
        )
    else:
        story.append(Paragraph("Nenhum resultado aprovado para este projeto.", _BODY))

    # ── Rodapé: assinatura + QR + hash ──────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    qr_cell = [
        _qr_flowable(verify_url),
        Paragraph("Verifique a autenticidade", _CENTER),
    ]
    sign_cell = [
        Paragraph("<b>Responsável técnico</b>", _BODY),
        Paragraph(_txt(signer), _BODY),
        Spacer(1, 3 * mm),
        Paragraph("<b>Assinado em</b>", _BODY),
        Paragraph(_txt(signed_at), _BODY),
        Spacer(1, 3 * mm),
        Paragraph("<b>SHA-256 do conteúdo</b>", _BODY),
        Paragraph(_txt(content_sha), _MONO),
        Spacer(1, 2 * mm),
        Paragraph(_txt(verify_url), _MONO),
    ]
    footer = Table([[sign_cell, qr_cell]], colWidths=[125 * mm, 40 * mm])
    footer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor("#1f3a5f")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(footer)

    doc.build(story)
    return buf.getvalue()
