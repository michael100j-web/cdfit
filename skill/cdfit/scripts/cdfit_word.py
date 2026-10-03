"""Word files with CD Fit graphs, without python-docx.

write_docx makes a .docx with the graph picture and the results table. The picture carries the add-in's alt
text (summary, a semicolon-separated copy of the data, and the #CDFIT-STATE settings), so the CD Fit add-in
opens it like a graph it inserted itself: click the picture with the add-in open, edit, Update selected graph.

read_graphs finds the CD Fit graphs in any .docx and returns their saved states.
"""
from __future__ import annotations

import json
import random
import re
import string
import zipfile
import xml.etree.ElementTree as ET

from cdfit_engine import GRAPH_TITLE, TAG

NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_WE = "http://schemas.microsoft.com/office/webextensions/webextension/2010/11"
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _esc(s, attr=False):
    s = _BAD_XML.sub("", str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if attr:
        s = s.replace('"', "&quot;").replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")
    return s


def new_graph_id():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def state_json(S):
    """JSON.stringify(S) as the add-in stores it."""
    return json.dumps(S, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


# ---------------------------------------------------------------- writing
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>{title}</dc:title><dc:creator>CD Fit</dc:creator></cp:coreProperties>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="200" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:i/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""

_DOC_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document '
             'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
             'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
             'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
             'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
             'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>')
_SECT = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1417" '
         'w:left="1417" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
_TEXT_WIDTH = 11906 - 2 * 1417   # twips


def _picture(n, rid, cx, cy, title, descr):
    return (f'<w:p><w:pPr><w:keepNext/><w:spacing w:after="120"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:docPr id="{n}" name="Picture {n}" descr="{_esc(descr, True)}" title="{_esc(title, True)}"/>'
            f'<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            f'<pic:nvPicPr><pic:cNvPr id="{n}" name="cdfit-graph-{n}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            f'</wp:inline></w:drawing></w:r></w:p>')


def _para(text, style=None, bold=False):
    """A heading or caption, kept on the same page as what follows it."""
    pstyle = f'<w:pStyle w:val="{style}"/>' if style else ""
    ppr = f"<w:pPr>{pstyle}<w:keepNext/></w:pPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{_esc(text)}</w:t></w:r></w:p>'


def _table(rows):
    """A bordered 10 pt table with a repeating header row, as the add-in's Insert results table gives."""
    ncol = max(len(r) for r in rows)
    first = 2800 if ncol > 1 else _TEXT_WIDTH
    other = min(2000, (_TEXT_WIDTH - first) // max(1, ncol - 1))
    widths = [first] + [other] * (ncol - 1)
    b = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    out = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
           + "".join(b.format(e) for e in ("top", "left", "bottom", "right", "insideH", "insideV"))
           + '</w:tblBorders><w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" '
             'w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid>'
           + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"]
    for k, row in enumerate(rows):
        out.append("<w:tr>" + ("<w:trPr><w:tblHeader/></w:trPr>" if k == 0 else ""))
        for j in range(ncol):
            cell = row[j] if j < len(row) else ""
            rpr = "<w:rPr>" + ("<w:b/>" if k == 0 else "") + '<w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'
            out.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[j]}" w:type="dxa"/></w:tcPr>'
                       f'<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
                       f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(cell)}</w:t></w:r></w:p></w:tc>')
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def write_docx(path, graphs, title="CD Fit graphs"):
    """graphs: list of dicts with png (bytes), width_px, height_px, width_cm, alt (descr), table (rows or None),
    caption (str or None), heading (str or None). Each graph gets the add-in's picture title and alt text."""
    body, rels, media = [], [], []
    for n, g in enumerate(graphs, start=1):
        rid = f"rIdImg{n}"
        cx = round(g["width_cm"] * 360000)
        cy = round(cx * g["height_px"] / g["width_px"])
        if g.get("heading"):
            body.append(_para(g["heading"], bold=True))
        body.append(_picture(n, rid, cx, cy, GRAPH_TITLE + g.get("id", new_graph_id()), g["alt"]))
        if g.get("caption"):
            body.append(_para(g["caption"], style="Caption"))
        if g.get("table") and len(g["table"][0]) > 1:
            body.append(_table(g["table"]))
            body.append('<w:p/>')
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    f'relationships/image" Target="media/cdfit-graph-{n}.png"/>')
        media.append((f"word/media/cdfit-graph-{n}.png", g["png"]))
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
                'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/styles" Target="styles.xml"/>' + "".join(rels) + "</Relationships>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("docProps/core.xml", _CORE.format(title=_esc(title)))
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", _DOC_HEAD + "".join(body) + _SECT)
        for name, data in media:
            z.writestr(name, data)


# ---------------------------------------------------------------- reading
def _backup_settings(z):
    """The add-in's backup copies ("cdfit:<id>" document settings) from the web extension parts."""
    out = {}
    for name in z.namelist():
        if re.fullmatch(r"word/webextensions/webextension\d*\.xml", name):
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for prop in root.iter(f"{{{NS_WE}}}property"):
                if (prop.get("name") or "").startswith("cdfit:"):
                    out[prop.get("name")] = prop.get("value")
    return out


def read_graphs(path):
    """Every CD Fit graph in a .docx, in document order: dicts with index, id, summary and state (or error)."""
    graphs = []
    with zipfile.ZipFile(path) as z:
        backups = _backup_settings(z)
        parts = sorted((n for n in z.namelist()
                        if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", n)),
                       key=lambda n: (n != "word/document.xml", n))
        for part in parts:
            root = ET.fromstring(z.read(part))
            for pr in root.iter(f"{{{NS_WP}}}docPr"):
                descr, title = pr.get("descr") or "", pr.get("title") or ""
                k, m = descr.find(TAG), title.find(GRAPH_TITLE)
                if k < 0 and m < 0:
                    continue
                gid = title[m + len(GRAPH_TITLE):].strip() if m >= 0 else ""
                g = {"index": len(graphs) + 1, "id": gid, "part": part, "summary": descr.split("\n", 1)[0]}
                state = None
                if k >= 0:
                    try:
                        state = json.loads(descr[k + len(TAG):])
                    except json.JSONDecodeError:
                        state = None
                if state is None and gid and ("cdfit:" + gid) in backups:
                    try:
                        v = json.loads(backups["cdfit:" + gid])
                        state = json.loads(v) if isinstance(v, str) else v
                    except (json.JSONDecodeError, TypeError):
                        state = None
                if isinstance(state, dict):
                    g["state"] = state
                else:
                    g["error"] = "The picture's saved CD Fit data could not be read."
                graphs.append(g)
    return graphs
