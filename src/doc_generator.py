"""Section 25: document generator -> one bundle per lender-month:
   <bundle>/pack.md       Markdown with the charts embedded (relative links) and a table-view link under each chart
   <bundle>/pack.pdf      the same content typeset for printing (A4, page numbers, run id in the footer)
   <bundle>/charts/*.png|csv|alt.txt, evidence.json, manifest.json (sha256 of every file + run ids + audit status)
The body text is the already-audited pack; the appendix (evidence ledger: SQL and attribution calls) is machine-written VERBATIM and is not prose."""
import json, hashlib, pathlib, re, shutil, datetime, html
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak, Preformatted
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
INK, INK2, GRID, SOFT = colors.HexColor("#0b0b0b"), colors.HexColor("#52514e"), colors.HexColor("#d9d7d2"), colors.HexColor("#f3f2ef")
BLUE = colors.HexColor("#2a78d6")
ST = {"body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK, spaceAfter=5, alignment=TA_LEFT),
      "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK, spaceBefore=12, spaceAfter=5),
      "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=8, spaceAfter=3),
      "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=INK, spaceAfter=4),
      "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=12, textColor=INK2, spaceAfter=3),
      "headline": ParagraphStyle("headline", fontName="Helvetica-Bold", fontSize=11.5, leading=16, textColor=INK, spaceAfter=0),
      "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK), "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=INK),
      "cap": ParagraphStyle("cap", fontName="Helvetica", fontSize=8, leading=10.5, textColor=INK2, spaceAfter=8), "li": ParagraphStyle("li", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK, leftIndent=14, firstLineIndent=-10, spaceAfter=3),
      "mono": ParagraphStyle("mono", fontName="Courier", fontSize=7.2, leading=9, textColor=INK, backColor=SOFT, borderPadding=3, spaceAfter=6)}
def inline(t):
    t = html.escape(t, quote=False); t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t); t = re.sub(r"`([^`]+)`", r'<font name="Courier" size="8.3">\1</font>', t)
    return re.sub(r"\[((?:[QA]\d{3}(?:,\s*)?)+)\]", r'<font color="#52514e" size="8">[\1]</font>', t)
def _table(rows):
    data = [[Paragraph(inline(c.strip()), ST["cellh" if i == 0 else "cell"]) for c in r.strip().strip("|").split("|")] for i, r in enumerate(rows) if not re.fullmatch(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?", r.strip())]
    n = len(data[0]); w = (174 * mm); first = min(0.34, 0.5 if n <= 2 else 0.22) * w; cw = [first] + [(w - first) / (n - 1)] * (n - 1) if n > 1 else [w]
    t = Table(data, colWidths=cw, repeatRows=1); t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 4)])); return [t, Spacer(1, 6)]
def _img(path, alt, csv_name):
    iw, ih = ImageReader(str(path)).getSize(); w = 174 * mm; h = w * ih / iw
    cap = html.escape(alt.split(". ")[0] + ".", quote=False) + f' <font color="#52514e">Table view: {html.escape(csv_name)}</font>'
    return KeepTogether([Image(str(path), width=w, height=h), Paragraph(cap, ST["cap"])])
def md_to_flowables(md, charts_by_section):
    out, lines, i, cur = [], md.split("\n"), 0, None
    def flush_charts():
        for c in charts_by_section.get(cur, []): out.append(_img(c["png"], c["alt"], c["csv_name"]))
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("# "): i += 1; continue                                                     # title/headline handled on the cover
        if ln.startswith("## "): flush_charts(); cur = ln[3:].strip(); out.append(Paragraph(inline(cur), ST["h2"])); i += 1; continue
        if ln.startswith("### "): out.append(Paragraph(inline(ln[4:]), ST["h3"])); i += 1; continue
        if ln.startswith("|"):
            blk = []
            while i < len(lines) and lines[i].startswith("|"): blk.append(lines[i]); i += 1
            out += _table(blk); continue
        if re.match(r"^\d+\.\s", ln) or ln.startswith("- "):
            m = re.match(r"^(\d+\.)\s(.*)", ln); out.append(Paragraph((m.group(1) + " " + inline(m.group(2))) if m else ("&bull; " + inline(ln[2:])), ST["li"])); i += 1; continue
        if ln.strip() == "": i += 1; continue
        blk = [ln]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||\d+\.\s|- )", lines[i]): blk.append(lines[i]); i += 1
        out.append(Paragraph(inline(" ".join(blk)), ST["body"]))
    flush_charts(); return out
class NumberedCanvas(canvas.Canvas):
    footer = ""
    def __init__(self, *a, **k): super().__init__(*a, **k); self._pages = []
    def showPage(self): self._pages.append(dict(self.__dict__)); self._startPage()
    def save(self):
        n = len(self._pages)
        for st in self._pages:
            self.__dict__.update(st); self.setFont("Helvetica", 7.5); self.setFillColor(INK2); self.drawString(18 * mm, 10 * mm, self.footer); self.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {n}"); super().showPage()
        super().save()
def evidence_md(evidence):
    out = ["## Appendix: evidence ledger", "", "Machine-written verbatim record of the queries and calculations cited above. It is not narrative and is not edited.", ""]
    for k in sorted(evidence):
        e = evidence[k]
        if k.startswith("Q"): out += [f"**{k}** {e.get('purpose', '')}", "", "```", e["sql"].strip(), "```", ""]
        else: out += [f"**{k}** attribution: " + json.dumps({a: e["args"][a] for a in ("month", "bucket_from", "metric", "product_type", "region", "recent_months", "baseline_lag", "causes", "control") if a in e.get("args", {})}, default=str), ""]
    return "\n".join(out)
SECTION_CHARTS = {"Outlook (3 months)": ["npa_outlook"], "Forecast by bucket": ["bucket_panels", "rate_forecast"], "What moved": ["what_moved"]}
def generate(pack, charts, evidence, meta, out_dir):
    """pack: build_pack() result; charts: {key: png path}; evidence: {id: ledger entry}; meta: lender, origin, run_id, audit."""
    out = pathlib.Path(out_dir); (out / "charts").mkdir(parents=True, exist_ok=True); md = pack["markdown"]; title_line = md.splitlines()[0][2:]
    cb = {}
    for sec, keys in SECTION_CHARTS.items():
        for k in keys:
            if k not in charts: continue
            src = pathlib.Path(charts[k]); [shutil.copy(src.with_suffix(s), out / "charts" / (src.stem + s)) for s in (".png", ".csv", ".alt.txt")]
            cb.setdefault(sec, []).append(dict(png=out / "charts" / (src.stem + ".png"), alt=src.with_suffix(".alt.txt").read_text(), csv_name=f"charts/{src.stem}.csv", stem=src.stem))
    # ---- markdown with embedded charts (inserted at the end of the section they belong to)
    parts = re.split(r"(?m)^(?=## )", md); mdout = [parts[0]]
    for p in parts[1:]:
        sec = p.splitlines()[0][3:].strip(); extra = "".join(f"\n\n![{c['alt'].split('. ')[0]}](charts/{c['stem']}.png)\n\n*Table view: [charts/{c['stem']}.csv](charts/{c['stem']}.csv)*" for c in cb.get(sec, []))
        mdout.append(p.rstrip() + extra + "\n\n")
    meta_line = f"Lender {meta['lender'][-1]} | data cut-off {pd.Timestamp(meta['origin']):%B %Y} | model run {meta['run_id']} | generated {meta['generated']}"
    md_full = "\n".join(["# " + title_line, "", f"*{meta_line}*", ""]) .replace("# " + title_line, "# " + title_line) + "\n" + "".join(mdout[1:]) + "\n" + evidence_md(evidence)
    (out / "pack.md").write_text(md_full); (out / "evidence.json").write_text(json.dumps(evidence, indent=1, default=str))
    # ---- PDF
    NumberedCanvas.footer = f"Lender {meta['lender'][-1]} | {pd.Timestamp(meta['origin']):%B %Y} | model run {meta['run_id']}"
    doc = SimpleDocTemplate(str(out / "pack.pdf"), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title=title_line, author="Roll-rate forecaster")
    story = [Paragraph(f"Roll-rate review pack: Lender {meta['lender'][-1]}, {pd.Timestamp(meta['origin']):%B %Y}", ST["title"]), Paragraph(meta_line.replace("|", "&middot;"), ST["meta"]), Spacer(1, 6)]
    box = Table([[Paragraph(inline(title_line), ST["headline"])]], colWidths=[174 * mm]); box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("LINEBEFORE", (0, 0), (0, -1), 3, BLUE), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [box, Spacer(1, 6)] + md_to_flowables(md, cb)
    story += [PageBreak(), Paragraph("Appendix: evidence ledger", ST["h2"]), Paragraph("Machine-written verbatim record of the queries and calculations cited above. It is not narrative and is not edited.", ST["meta"])]
    for k in sorted(evidence):
        e = evidence[k]
        if k.startswith("Q"): story += [Paragraph(f"<b>{k}</b> " + html.escape(e.get("purpose", ""), quote=False), ST["body"]), Preformatted(e["sql"].strip()[:900], ST["mono"])]
        else: story += [Paragraph(f"<b>{k}</b> attribution: " + html.escape(json.dumps({a: e["args"][a] for a in ("month", "bucket_from", "metric", "region", "recent_months", "baseline_lag", "causes") if a in e.get("args", {})}, default=str)[:600], quote=False), ST["body"])]
    doc.build(story, canvasmaker=NumberedCanvas)
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    man = {"lender": meta["lender"], "origin": str(meta["origin"])[:7], "model_run": meta["run_id"], "generated": meta["generated"], "audit": meta.get("audit"), "files": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (out / "manifest.json").write_text(json.dumps(man, indent=1)); return {"dir": str(out), "md": str(out / "pack.md"), "pdf": str(out / "pack.pdf"), "manifest": man}
