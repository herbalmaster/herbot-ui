#!/usr/bin/env python3
"""Draw a TMH workflow diagram as a plain SVG (D509, standards 24).

    python flow_diagram.py flow.json [-o flow.svg]
    python flow_diagram.py --legend [-o legend.svg]

One library for every workflow diagram in TMH. Each chat turns its own system's definition (Resend, n8n, Odoo)
into the neutral flow format (flow.schema.json) and runs this; the step kinds, shapes, colours and names come only
from step-kinds.json, so a diagram means the same thing everywhere.

The SVG is plain shapes and <text> (no fonts to load, no scripts, no foreignObject), so it shows the same as an
image in an Odoo Knowledge article, in print and inline in a web page. It is always 676 px wide, which fits an A4
page and an article without shrinking the 14 px text. Flows run top to bottom; a flow that needs more than three
columns, or a label longer than three lines, is refused: split it into another flow (a "subflow" step) or shorten
the words.

No dependencies beyond the Python standard library.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
from xml.sax.saxutils import escape

HERE = pathlib.Path(__file__).resolve().parent
KINDS_FILE = HERE / "step-kinds.json"

NODE_W = 196
COL_GAP = 28
MARGIN = 12
RANK_GAP = 46
LINE_H = 18
PAD_Y = 12
DOT_R = 13
MAX_LINES = 3

# Refuse anything that looks like a key, token or private webhook address (standards 24: SOP images are seen by staff).
SECRETISH = re.compile(r"(?i)(webhook|token=|api[_-]?key|secret|password|sk-ant-|ghp_|shpat_|key=[A-Za-z0-9]{12,})")

# Approximate Arial advance widths in em (the font an <img> SVG falls back to on Windows; Lato is narrower).
_W = {**{c: 0.5 for c in "abcdeghknopqsuvxyz"}, **{c: 0.28 for c in "fijlrt"}, "m": 0.83, "w": 0.72,
      **{c: 0.67 for c in "ABCDEFGHKNOPQRSUVXYZ"}, **{c: 0.3 for c in "IJ"}, "L": 0.56, "M": 0.83, "T": 0.61,
      "W": 0.94, **{c: 0.556 for c in "0123456789"}, " ": 0.28, ".": 0.28, ",": 0.28, ":": 0.28, ";": 0.28,
      "'": 0.19, "-": 0.33, "%": 0.89, "&": 0.67, "(": 0.33, ")": 0.33, "/": 0.28, "?": 0.56, "·": 0.28}


def text_w(s, px):
    return sum(_W.get(c, 0.6) for c in s) * px


def wrap(s, px, width):
    words, lines, cur = str(s).split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_w(trial, px) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def load_kinds():
    return json.loads(KINDS_FILE.read_text(encoding="utf-8"))


class FlowError(ValueError):
    pass


def check_flow(flow, kinds):
    if not isinstance(flow.get("steps"), list) or not flow["steps"]:
        raise FlowError("the flow has no steps")
    ids = set()
    for s in flow["steps"]:
        sid = s.get("id")
        if not sid or sid in ids:
            raise FlowError(f"step id missing or used twice: {sid!r}")
        ids.add(sid)
        if s.get("kind") not in kinds:
            raise FlowError(f"step {sid}: unknown kind {s.get('kind')!r}; use one of {', '.join(kinds)}")
        for field in ("label", "note", "link"):
            if s.get(field) and SECRETISH.search(str(s[field])):
                raise FlowError(f"step {sid}: its {field} looks like it carries a key, token or webhook address")
    for s in flow["steps"]:
        for e in edges_of(s):
            if e["to"] not in ids:
                raise FlowError(f"step {s['id']}: next step {e['to']!r} does not exist")
    for field in ("title", "source"):
        if flow.get(field) and SECRETISH.search(str(flow[field])):
            raise FlowError(f"the flow's {field} looks like it carries a key, token or webhook address")


def edges_of(step):
    nxt = step.get("next") or []
    if isinstance(nxt, str):
        nxt = [nxt]
    return [{"to": e} if isinstance(e, str) else e for e in nxt]


def layout(flow, kinds, page):
    steps = {s["id"]: s for s in flow["steps"]}
    order = [s["id"] for s in flow["steps"]]
    parents = {k: [] for k in steps}
    for s in flow["steps"]:
        for e in edges_of(s):
            parents[e["to"]].append(s["id"])

    # Rank = longest path from a start step; a loop back is refused (draw it as a "subflow" or a note instead).
    rank, visiting = {}, set()

    def depth(k):
        if k in rank:
            return rank[k]
        if k in visiting:
            raise FlowError(f"the flow loops back at step {k}; draw a repeat as a note or another flow")
        visiting.add(k)
        rank[k] = 1 + max((depth(p) for p in parents[k]), default=-1)
        visiting.discard(k)
        return rank[k]

    for k in order:
        depth(k)

    # Columns: a step stays in its first parent's column; another way out, or a step reached from several
    # places, takes the next free column to the right.
    col, next_col = {}, [0]

    def place(k, c):
        if k in col:
            return
        col[k] = c
        for i, e in enumerate(edges_of(steps[k])):
            child = e["to"]
            if child in col:
                continue
            if i == 0 and len(parents[child]) == 1:
                place(child, c)
            else:
                next_col[0] += 1
                place(child, next_col[0])

    for k in order:
        if not parents[k]:
            if col:
                next_col[0] += 1
            place(k, next_col[0])
    n_cols = next_col[0] + 1
    if n_cols > page["max_columns"]:
        raise FlowError(f"the flow needs {n_cols} columns; at most {page['max_columns']} fit an A4 page. "
                        "Fold identical branches into one (with market tags) or move a branch into another flow")

    # Sizes.
    px, inner = page["label_px"], NODE_W - 24
    box = {}
    for k, s in steps.items():
        shape = kinds[s["kind"]]["shape"]
        width = inner - (40 if shape == "diamond" else 16 if shape == "hexagon" else 0)
        if shape == "dot":
            width = NODE_W / 2 + COL_GAP - DOT_R - 12
        lines = wrap(s.get("label", ""), px, width)
        if s.get("tags"):
            lines_small = [" · ".join(str(t).upper() for t in s["tags"])]
        else:
            lines_small = []
        if s.get("note"):
            lines_small += wrap(s["note"], page["small_px"], width)
        if len(lines) > MAX_LINES:
            raise FlowError(f"step {k}: the words take {len(lines)} lines; at most {MAX_LINES}. Shorten them")
        h = PAD_Y * 2 + LINE_H * len(lines) + 16 * len(lines_small)
        if shape == "diamond":
            h += 28
        if shape == "dot":
            h = max(2 * DOT_R, LINE_H * len(lines) + 16 * len(lines_small))
        box[k] = {"lines": lines, "small": lines_small, "h": max(h, 44 if shape != "dot" else 2 * DOT_R)}

    n_ranks = max(rank.values()) + 1
    rank_h = [max([box[k]["h"] for k in steps if rank[k] == r] or [0]) for r in range(n_ranks)]
    top = MARGIN + (34 if flow.get("title") else 0)
    rank_y, y = [], top
    for r in range(n_ranks):
        rank_y.append(y)
        y += rank_h[r] + RANK_GAP
    for k in steps:
        b = box[k]
        b["x"] = MARGIN + col[k] * (NODE_W + COL_GAP)
        b["y"] = rank_y[rank[k]] + (rank_h[rank[k]] - b["h"]) / 2
        b["cx"] = b["x"] + NODE_W / 2
    return steps, box, y - RANK_GAP


def node_svg(s, b, kind, page):
    shape, x, y, w, h = kind["shape"], b["x"], b["y"], NODE_W, b["h"]
    dash = f' stroke-dasharray="{kind["dash"]}"' if kind.get("dash") else ""
    st = f'fill="{kind["fill"]}" stroke="{kind["stroke"]}" stroke-width="1.5"{dash}'
    out = []
    if shape == "rounded":
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" {st}/>')
    elif shape in ("box", "double"):
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" {st}/>')
        if shape == "double":
            out.append(f'<rect x="{x + 4}" y="{y + 4}" width="{w - 8}" height="{h - 8}" rx="2" fill="none" '
                       f'stroke="{kind["stroke"]}" stroke-width="1"/>')
    elif shape == "pill":
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{min(h / 2, 22)}" {st}/>')
    elif shape == "hexagon":
        i = 14
        pts = f"{x + i},{y} {x + w - i},{y} {x + w},{y + h / 2} {x + w - i},{y + h} {x + i},{y + h} {x},{y + h / 2}"
        out.append(f'<polygon points="{pts}" {st}/>')
    elif shape == "diamond":
        cx, cy = x + w / 2, y + h / 2
        out.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" {st}/>')
    if shape == "dot":
        cy = y + h / 2
        out.append(f'<circle cx="{x + w / 2}" cy="{cy}" r="{DOT_R}" {st}/>')
        tx, anchor, colour = x + w / 2 + DOT_R + 8, "start", page["ink"]
        rows = [(l, page["label_px"], "600") for l in b["lines"]] + [(l, page["small_px"], "400") for l in b["small"]]
        ty = cy - (LINE_H * len(b["lines"]) + 16 * len(b["small"])) / 2
    else:
        tx, anchor, colour = x + w / 2, "middle", kind["text"]
        rows = [(l, page["label_px"], "600") for l in b["lines"]] + [(l, page["small_px"], "400") for l in b["small"]]
        ty = y + (h - (LINE_H * len(b["lines"]) + 16 * len(b["small"]))) / 2
    for text, px, weight in rows:
        step = LINE_H if px == page["label_px"] else 16
        out.append(f'<text x="{tx}" y="{ty + step / 2}" text-anchor="{anchor}" dominant-baseline="central" '
                   f'font-size="{px}" font-weight="{weight}" fill="{colour}">{escape(text)}</text>')
        ty += step
    body = "\n".join(out)
    if s.get("link"):
        body = f'<a href="{escape(s["link"])}" target="_blank"><title>{escape(s.get("label", ""))}</title>{body}</a>'
    return body


def edge_svg(a, b, label, page):
    line = page["line"]
    out = []
    if abs(a["cx"] - b["cx"]) < 1:
        x, y1, y2 = a["cx"], a["y"] + a["h"], b["y"] - 2
        out.append(f'<path d="M{x} {y1} L{x} {y2}" fill="none" stroke="{line}" stroke-width="1.3" marker-end="url(#ah)"/>')
        if label:
            out.append(f'<text x="{x + 7}" y="{y1 + 14}" font-size="{page["small_px"]}" fill="{page["muted"]}">'
                       f'{escape(label)}</text>')
    else:
        right = b["cx"] > a["cx"]
        sx = a["x"] + NODE_W if right else a["x"]
        sy = a["y"] + a["h"] / 2
        out.append(f'<path d="M{sx} {sy} L{b["cx"]} {sy} L{b["cx"]} {b["y"] - 2}" fill="none" stroke="{line}" '
                   f'stroke-width="1.3" marker-end="url(#ah)"/>')
        if label:
            out.append(f'<text x="{b["cx"] + 7}" y="{sy + 16}" font-size="{page["small_px"]}" '
                       f'fill="{page["muted"]}">{escape(label)}</text>')
    return "\n".join(out)


def legend_svg(used, kinds, page, y0):
    """A key of the kinds this diagram uses, two to a row."""
    out, per_row, cell = [], 2, (page["width"] - 2 * MARGIN) / 2
    out.append(f'<line x1="{MARGIN}" y1="{y0}" x2="{page["width"] - MARGIN}" y2="{y0}" stroke="#D5DACB"/>')
    y0 += 14
    for i, k in enumerate(used):
        kind = kinds[k]
        x = MARGIN + (i % per_row) * cell
        y = y0 + (i // per_row) * 30
        dash = f' stroke-dasharray="{kind["dash"]}"' if kind.get("dash") else ""
        st = f'fill="{kind["fill"]}" stroke="{kind["stroke"]}" stroke-width="1.3"{dash}'
        sh = kind["shape"]
        if sh == "dot":
            out.append(f'<circle cx="{x + 15}" cy="{y + 10}" r="8" {st}/>')
        elif sh == "diamond":
            out.append(f'<polygon points="{x + 15},{y} {x + 30},{y + 10} {x + 15},{y + 20} {x},{y + 10}" {st}/>')
        elif sh == "hexagon":
            out.append(f'<polygon points="{x + 5},{y} {x + 25},{y} {x + 30},{y + 10} {x + 25},{y + 20} {x + 5},{y + 20} '
                       f'{x},{y + 10}" {st}/>')
        else:
            rx = {"rounded": 5, "pill": 10}.get(sh, 2)
            out.append(f'<rect x="{x}" y="{y}" width="30" height="20" rx="{rx}" {st}/>')
            if sh == "double":
                out.append(f'<rect x="{x + 3}" y="{y + 3}" width="24" height="14" rx="1" fill="none" '
                           f'stroke="{kind["stroke"]}"/>')
        out.append(f'<text x="{x + 38}" y="{y + 10}" dominant-baseline="central" font-size="{page["small_px"]}" '
                   f'fill="{page["ink"]}"><tspan font-weight="600">{escape(kind["name"])}</tspan>'
                   f'<tspan fill="{page["muted"]}">: {escape(kind["means"])}</tspan></text>')
    rows = (len(used) + per_row - 1) // per_row
    return "\n".join(out), y0 + rows * 30


def render(flow, kinds_doc=None, today=None):
    kinds_doc = kinds_doc or load_kinds()
    kinds, page = kinds_doc["kinds"], kinds_doc["page"]
    check_flow(flow, kinds)
    steps, box, bottom = layout(flow, kinds, page)
    W = page["width"]
    parts = []
    if flow.get("title"):
        parts.append(f'<text x="{MARGIN}" y="{MARGIN + 14}" font-size="16" font-weight="700" fill="{page["title"]}">'
                     f'{escape(flow["title"])}</text>')
    for s in flow["steps"]:
        for e in edges_of(s):
            parts.append(edge_svg(box[s["id"]], box[e["to"]], e.get("label"), page))
    for s in flow["steps"]:
        parts.append(node_svg(s, box[s["id"]], kinds[s["kind"]], page))
    used = [k for k in kinds if any(s["kind"] == k for s in flow["steps"])]
    leg, y = legend_svg(used, kinds, page, bottom + 22)
    parts.append(leg)
    made = flow.get("made") or (today or datetime.date.today()).strftime("%d %b %Y").lstrip("0")
    foot = f"Made {made}" + (f" · Source: {flow['source']}" if flow.get("source") else "")
    if text_w(foot, 11) > W - 2 * MARGIN:
        foot = f"Made {made} · Source in GitHub (link under the image)"
    parts.append(f'<text x="{MARGIN}" y="{y + 8}" font-size="11" fill="{page["muted"]}">{escape(foot)}</text>')
    H = int(y + 20)
    title = escape(flow.get("title") or "Workflow diagram")
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'font-family="{page["font"]}"><title>{title}</title>'
            f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M1 1L9 5L1 9z" fill="{page["line"]}"/></marker></defs>'
            f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')
    return head + "\n" + "\n".join(parts) + "\n</svg>\n"


def legend_only(kinds_doc=None):
    kinds_doc = kinds_doc or load_kinds()
    kinds, page = kinds_doc["kinds"], kinds_doc["page"]
    leg, y = legend_svg(list(kinds), kinds, page, MARGIN)
    W, H = page["width"], int(y + 6)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'font-family="{page["font"]}"><title>Workflow diagram key</title>'
            f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>\n{leg}\n</svg>\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("flow", nargs="?", help="flow JSON file (flow.schema.json)")
    ap.add_argument("-o", "--out", help="write the SVG here (default: print it)")
    ap.add_argument("--legend", action="store_true", help="draw the key of every step kind")
    a = ap.parse_args(argv)
    try:
        if a.legend:
            svg = legend_only()
        elif a.flow:
            svg = render(json.loads(pathlib.Path(a.flow).read_text(encoding="utf-8")))
        else:
            ap.error("give a flow file or --legend")
    except FlowError as e:
        print(f"flow_diagram: refused: {e}", file=sys.stderr)
        return 2
    if a.out:
        pathlib.Path(a.out).write_text(svg, encoding="utf-8")
        print(f"flow_diagram: ok, wrote {a.out}")
    else:
        sys.stdout.write(svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
