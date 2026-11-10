"""Build the fitcher architecture diagram from one layout.

Writes docs/finch-architecture.excalidraw (all sections, editable in Excalidraw)
and one SVG per section under docs/architecture/ for the README.
Run from the repository root: python scripts/build_architecture_diagram.py
"""

import base64
import hashlib
import json
import random
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCALIDRAW = ROOT / "docs" / "finch-architecture.excalidraw"
SVG_DIR = ROOT / "docs" / "architecture"

# Brand colours from docs/brand/README.md.
INK = "#111111"
PAPER = "#FFFFFF"
MIST = "#E8E8EA"
GRAPHITE = "#6B6B70"
CANVAS = "#F6F6F7"
MUTED = GRAPHITE
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
# Box kinds: a step of the product (white card, ink icon cell), an outcome that
# leaves the main path (ghost card, mist icon cell) and the answer (ink card,
# like the round dot of the logo).
KINDS = {
    "step": dict(fill=PAPER, stroke=MIST, cell=INK, glyph=PAPER, title=INK, sub=GRAPHITE, dashed=False),
    "ghost": dict(fill=CANVAS, stroke="#C9C9CE", cell=MIST, glyph=INK, title=INK, sub=GRAPHITE, dashed=True),
    "answer": dict(fill=INK, stroke=INK, cell=PAPER, glyph=INK, title=PAPER, sub="#C9C9CE", dashed=False),
}
SYMBOL = ('<rect x="28" y="28" width="56" height="56" rx="14"/><rect x="100" y="28" width="56" height="56" rx="14"/>'
          '<rect x="172" y="28" width="56" height="56" rx="14"/><rect x="28" y="100" width="56" height="56" rx="14"/>'
          '<rect x="100" y="100" width="56" height="56" rx="14"/><rect x="28" y="172" width="56" height="56" rx="14"/>'
          '<circle cx="200" cy="200" r="24"/>')
LOGO = ROOT / "docs" / "brand" / "svg" / "fitcher-horizontal.svg"

# 24x24 line icons, drawn for this diagram.
ICONS = {
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "server": '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/>'
              '<path d="M7 6.5h.01M7 17.5h.01"/>',
    "sparkles": '<path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/>'
                '<path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8z"/>',
    "route": '<circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/>'
             '<path d="M7.5 12h4l5-6M11.5 12l5 6"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
                '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "plug": '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h6"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "shieldcheck": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "message": '<path d="M21 12a8 8 0 0 1-8 8H4l2.5-3A8 8 0 1 1 21 12z"/>',
    "bulb": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
    "book": '<path d="M4 19V5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2z"/><path d="M4 19a2 2 0 0 0 2 2h14"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M8 17v-5M13 17V8M18 17V5"/>',
    "lines": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "stop": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 2.9-6 6.5-6s6.5 2.5 6.5 6"/>'
             '<path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2.2.6 3.5 2.6 3.5 6"/>',
    "flask": '<path d="M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3"/><path d="M7 15h10"/>',
    "package": '<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3v5h5"/>'
               '<path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 21v-5h-5"/>',
    "pulse": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "pen": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "live": '<circle cx="12" cy="12" r="2"/><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4'
            'M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>',
}


def icon_svg(name, color, size=48):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{ICONS[name]}</svg>')


class Section:
    """One diagram section in local coordinates; boxes, arrows and notes."""

    def __init__(self, key, title, width):
        self.key, self.title, self.width = key, title, width
        self.boxes, self.arrows, self.notes = {}, [], []

    def box(self, id_, x, y, w, h, icon, title, sub, color):
        self.boxes[id_] = dict(x=x, y=y, w=w, h=h, icon=icon, title=title, sub=sub, kind=color)

    def arrow(self, a, b, label=None, via=None, start=None, end=None, color=GRAPHITE, dashed=False, label_at=None):
        A, B = self.boxes[a], self.boxes[b]
        if start is None or end is None:
            ax, ay = A["x"] + A["w"] / 2, A["y"] + A["h"] / 2
            bx, by = B["x"] + B["w"] / 2, B["y"] + B["h"] / 2
            if abs(ay - by) < 1:  # same row
                s = (A["x"] + A["w"], ay) if bx > ax else (A["x"], ay)
                e = (B["x"], by) if bx > ax else (B["x"] + B["w"], by)
            else:  # same column
                s = (ax, A["y"] + A["h"]) if by > ay else (ax, A["y"])
                e = (bx, B["y"]) if by > ay else (bx, B["y"] + B["h"])
            start, end = start or s, end or e
        pts = [start, *(via or []), end]
        if label and label_at is None:
            (sx, sy), (ex, ey) = max(zip(pts, pts[1:]), key=lambda p: abs(p[1][0] - p[0][0]) + abs(p[1][1] - p[0][1]))
            label_at = ((sx + ex) / 2, (sy + ey) / 2 - 12) if sy == ey else ((sx + ex) / 2 + 10, (sy + ey) / 2)
        self.arrows.append(dict(a=a, b=b, pts=pts, label=label, color=color, dashed=dashed, label_at=label_at,
                                anchor="middle" if pts[0][1] == pts[-1][1] or label_at is None else "start"))

    def note(self, x, y, text, size=15, color=MUTED):
        self.notes.append(dict(x=x, y=y, text=text, size=size, color=color))

    @property
    def height(self):
        bottom = max(b["y"] + b["h"] for b in self.boxes.values())
        for a in self.arrows:
            bottom = max(bottom, *(p[1] for p in a["pts"]))
        for n in self.notes:
            bottom = max(bottom, n["y"] + n["size"] * 1.4 * (n["text"].count("\n") + 1))
        return bottom + 20


# ------------------------------------------------------------------ layout

def grid(cols, w, gap):
    return [i * (w + gap) for i in range(cols)]


def system():
    s = Section("system", "1. How the pieces fit together", 1280)
    W, H = 200, 120
    c = grid(5, W, 70)
    r = [60, 250, 440]
    s.box("search", c[2], r[0], W, H, "search", "Search index", "Finds terms, metrics\nand examples (Qdrant)", "step")
    s.box("pack", c[3], r[0], W, H, "file", "Domain Pack", "A company's terms,\nmetrics and access rules", "step")
    s.box("user", c[0], r[1], W, H, "user", "User", "Asks in English\nor Vietnamese", "step")
    s.box("web", c[1], r[1], W, H, "monitor", "Web app", "Chat and\nworkspace console", "step")
    s.box("api", c[2], r[1], W, H, "server", "API and agent", "Understands the question\nand writes the SQL", "step")
    s.box("gateway", c[3], r[1], W, H, "route", "LLM gateway", "Sends each task to\nthe right model (LiteLLM)", "step")
    s.box("models", c[4], r[1], W, H, "sparkles", "AI models", "OpenAI, Anthropic,\nGemini or a local model", "step")
    s.box("signin", c[1], r[2], W, H, "lock", "Sign-in", "Accounts and roles\n(Keycloak)", "step")
    s.box("dw", c[2], r[2], W, H, "database", "Data warehouse", "Company data and\nrun logs (ClickHouse)", "step")
    s.box("sources", c[3], r[2], W, H, "plug", "Company sources", "Databases and files,\ncopied or read live", "step")
    s.arrow("user", "web", "asks")
    s.arrow("web", "api", "streams")
    s.arrow("api", "gateway", "AI tasks")
    s.arrow("gateway", "models")
    s.arrow("web", "signin", "signs in")
    s.arrow("api", "search", "looks up")
    s.arrow("api", "dw", "runs SQL")
    s.arrow("sources", "dw", "loads")
    s.arrow("pack", "search", "indexed")
    s.note(0, 590, "Everything runs in Docker Compose on one machine. Publishing a Domain Pack also writes the "
                   "database permissions for each role.")
    return s


def flow():
    s = Section("question-flow", "2. How a question is answered", 1280)
    W, H = 200, 120
    c = grid(5, W, 70)
    r = [60, 250, 470]
    s.box("blocked", c[1], r[0], W, H, "stop", "Blocked", "Unsafe input\nstops here", "ghost")
    s.box("quick", c[2], r[0], W, H, "message", "Quick reply", "Definitions, chart changes\nor off-topic questions", "ghost")
    s.box("clarify", c[4], r[0], W, H, "help", "Clarify or deny", "Ask which one was meant,\nor refuse politely", "ghost")
    s.box("q", c[0], r[1], W, H, "message", "Question", "Typed in the chat\nor on the command line", "step")
    s.box("safety", c[1], r[1], W, H, "shield", "Safety check", "Screens for prompt\ninjection first", "step")
    s.box("understand", c[2], r[1], W, H, "bulb", "Understand", "What is measured,\nfor which period", "step")
    s.box("terms", c[3], r[1], W, H, "book", "Match terms", "Maps words to the\ncompany's metrics", "step")
    s.box("perm", c[4], r[1], W, H, "shieldcheck", "Permission check", "Is the question clear,\nand may this role see it?", "step")
    s.box("sql", c[4], r[2], W, H, "code", "Write SQL", "One read-only query", "step")
    s.box("run", c[3], r[2], W, H, "play", "Check and run", "Validated, then run\nas the user's role", "step")
    s.box("chart", c[2], r[2], W, H, "chart", "Pick a chart", "Chosen by rules\nfrom the result shape", "step")
    s.box("summary", c[1], r[2], W, H, "lines", "Summarize", "Explains the rows in\nthe question's language", "step")
    s.box("answer", c[0], r[2], W, H, "check", "Answer", "SQL, table, chart\nand summary", "answer")
    for a, b in [("q", "safety"), ("safety", "understand"), ("understand", "terms"), ("terms", "perm"),
                 ("perm", "sql"), ("sql", "run"), ("run", "chart"), ("chart", "summary"), ("summary", "answer")]:
        s.arrow(a, b)
    s.arrow("safety", "blocked")
    s.arrow("understand", "quick")
    s.arrow("perm", "clarify")
    run, sql = s.boxes["run"], s.boxes["sql"]
    yb = r[2] + H
    s.arrow("run", "sql", "on an error: fix and retry, up to 3 times", dashed=True,
            start=(run["x"] + W / 2 + 40, yb), end=(sql["x"] + W / 2, yb),
            via=[(run["x"] + W / 2 + 40, yb + 40), (sql["x"] + W / 2, yb + 40)],
            label_at=(run["x"] + W / 2 + 175, yb + 62))
    s.note(0, 680, "The answer streams to the screen step by step. Numbers always come from the database, "
                   "never from the AI model.")
    return s


def access():
    s = Section("access-control", "3. Who can see what", 1280)
    W, H = 184, 130
    c = grid(6, W, 35)
    r = [60, 260, 460]
    s.box("rules", c[3], r[0], c[4] + W - c[3], 125, "file", "Access rules", "One policy file per company sets each role's\n"
                                                                   "tables, columns and rows", "step")
    s.box("user", c[0], r[1], W, H, "user", "Signed-in user", "Asks with one\nof their roles", "step")
    s.box("l0", c[1], r[1], W, H, "shield", "Safety screen", "Layer 0: before\nany AI model call", "step")
    s.box("l1", c[2], r[1], W, H, "search", "Role-aware search", "Layer 1: context\nlimited to the role", "step")
    s.box("l2", c[3], r[1], W, H, "shieldcheck", "Permission check", "Layer 2: refuses\nbefore any SQL", "step")
    s.box("l3", c[4], r[1], W, H, "lock", "Database rules", "Layer 3: the real\nsecurity boundary", "step")
    s.box("data", c[5], r[1], W, H, "database", "Data", "Only what the\nrole may read", "step")
    s.box("audit", c[3], r[2], c[4] + W - c[3], 125, "eye", "Audit log", "Every allow and deny is recorded\n"
                                                                "and shown to admins", "step")
    for a, b in [("user", "l0"), ("l0", "l1"), ("l1", "l2"), ("l2", "l3"), ("l3", "data")]:
        s.arrow(a, b)
    rules, audit = s.boxes["rules"], s.boxes["audit"]
    for lid in ("l2", "l3"):
        x = s.boxes[lid]["x"] + W / 2
        s.arrow("rules", lid, start=(x, rules["y"] + rules["h"]), end=(x, r[1]))
        s.arrow(lid, "audit", start=(x, r[1] + H), end=(x, audit["y"]))
    s.note(0, 470, "Layer 1 only keeps the AI's context small and relevant.\n"
                   "Layer 3, the database's own grants and row\nfilters, is what actually enforces access.")
    return s


def onboarding():
    s = Section("onboarding", "4. Bringing in a new company", 1280)
    W, H = 160, 140
    c = grid(7, W, 27)
    r = [60, 270]
    steps = [
        ("connect", "plug", "Connect data", "Copy it in\nor read it live", "step"),
        ("profile", "pulse", "Profile", "Measure tables,\ndates and values", "step"),
        ("docs", "file", "Add documents", "Manuals, policies,\nglossaries", "step"),
        ("draft", "pen", "Draft the pack", "AI proposes terms\nand metrics", "step"),
        ("review", "users", "Review", "A person approves\neach item", "step"),
        ("publish", "package", "Publish", "Search index and\npermissions", "step"),
        ("test", "flask", "Test", "Must answer 80%\nof eval questions", "step"),
    ]
    for i, (id_, icon, title, sub, color) in enumerate(steps):
        s.box(id_, c[i], r[0], W, H, icon, title, sub, color)
    for (a, *_), (b, *_) in zip(steps, steps[1:]):
        s.arrow(a, b)
    s.box("live", c[6], r[1], W, H, "live", "Live", "Answers the\ncompany's questions", "answer")
    s.box("feedback", c[4], r[1], W, H, "refresh", "Learn", "Disliked answers\nbecome new examples", "step")
    s.arrow("test", "live", "passes")
    s.arrow("live", "feedback", "feedback")
    s.arrow("feedback", "review")
    s.note(0, 290, "No engine code changes per company.\nThe Iowa Liquor Sales pack went through\n"
                   "these steps from a PostgreSQL database.")
    return s


def tracing():
    s = Section("tracing", "5. Every run is traced", 1280)
    W, H = 300, 130
    c = [0, 490, 980]
    s.box("run", c[0], 60, W, H, "message", "Each question", "Gets one trace id that\nfollows it through every step", "step")
    s.box("store", c[1], 60, W, H, "database", "Run log", "Steps, SQL, AI calls, cost\nand access decisions", "step")
    s.box("console", c[2], 60, W, H, "layout", "Workspace console", "Runs, Audit, Costs,\nFeedback and Evaluation", "step")
    s.arrow("run", "store", "written as it runs")
    s.arrow("store", "console", "read by admins and reviewers")
    s.note(0, 215, "Run logs and conversations are kept for 90 days.")
    return s


SECTIONS = [system(), flow(), access(), onboarding(), tracing()]


# ------------------------------------------------------------------ SVG

def text_width(s, size):
    return len(s) * size * 0.56


def svg_section(sec):
    pad = 36
    W, H = sec.width + 2 * pad, sec.height + 2 * pad
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="{-pad} {-pad} {W:.0f} {H:.0f}" font-family="{FONT}">',
           f'<title>{escape(sec.title)}</title>',
           f'<rect x="{-pad}" y="{-pad}" width="{W:.0f}" height="{H:.0f}" rx="18" fill="{CANVAS}"/>',
           '<defs>']
    colors = sorted({a["color"] for a in sec.arrows})
    for i, col in enumerate(colors):
        out.append(f'<marker id="head{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                   f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    out.append('</defs>')
    heads = {col: f"head{i}" for i, col in enumerate(colors)}
    # brand symbol next to the section title
    out.append(f'<g transform="translate(0,2) scale(0.125)" fill="{INK}">{SYMBOL}</g>')
    out.append(f'<text x="44" y="26" font-size="24" font-weight="600" fill="{INK}">{escape(sec.title)}</text>')
    for a in sec.arrows:
        pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in a["pts"])
        dash = ' stroke-dasharray="6 5"' if a["dashed"] else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{a["color"]}" stroke-width="1.8"{dash} '
                   f'stroke-linejoin="round" marker-end="url(#{heads[a["color"]]})"/>')
    for b in sec.boxes.values():
        k = KINDS[b["kind"]]
        cx = b["x"] + b["w"] / 2
        dash = ' stroke-dasharray="6 5"' if k["dashed"] else ""
        out.append(f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="14" fill="{k["fill"]}" '
                   f'stroke="{k["stroke"]}" stroke-width="1.5"{dash}/>')
        out.append(f'<rect x="{cx - 19}" y="{b["y"] + 12}" width="38" height="38" rx="10" fill="{k["cell"]}"/>')
        out.append(f'<svg x="{cx - 12}" y="{b["y"] + 19}" width="24" height="24" viewBox="0 0 24 24" fill="none" '
                   f'stroke="{k["glyph"]}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
                   f'{ICONS[b["icon"]]}</svg>')
        out.append(f'<text x="{cx}" y="{b["y"] + 72}" font-size="16.5" font-weight="600" fill="{k["title"]}" '
                   f'text-anchor="middle">{escape(b["title"])}</text>')
        for i, line in enumerate(b["sub"].split("\n")):
            out.append(f'<text x="{cx}" y="{b["y"] + 93 + i * 18}" font-size="13.5" fill="{k["sub"]}" '
                       f'text-anchor="middle">{escape(line)}</text>')
    for a in sec.arrows:
        if a["label"]:
            x, y = a["label_at"]
            out.append(f'<text x="{x:.0f}" y="{y:.0f}" font-size="13" fill="{GRAPHITE}" '
                       f'text-anchor="{a["anchor"]}">{escape(a["label"])}</text>')
    for n in sec.notes:
        for i, line in enumerate(n["text"].split("\n")):
            out.append(f'<text x="{n["x"]}" y="{n["y"] + n["size"] + i * n["size"] * 1.4:.0f}" '
                       f'font-size="{n["size"]}" fill="{n["color"]}">{escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ Excalidraw

class Excalidraw:
    def __init__(self):
        self.elements, self.files, self.n = [], {}, 0
        self.rng = random.Random(7)

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def _base(self, type_, x, y, w, h, **kw):
        e = {"id": kw.pop("id", None) or self._id(type_[:2]), "type": type_, "x": x, "y": y, "width": w, "height": h,
             "angle": 0, "strokeColor": INK, "backgroundColor": "transparent", "fillStyle": "solid",
             "strokeWidth": 2, "strokeStyle": "solid", "roughness": 0, "opacity": 100, "groupIds": [],
             "frameId": None, "roundness": None, "seed": self.rng.randint(1, 2**31),
             "version": 1, "versionNonce": self.rng.randint(1, 2**31), "isDeleted": False,
             "boundElements": [], "updated": 1, "link": None, "locked": False}
        e.update(kw)
        self.elements.append(e)
        return e

    def text(self, cx_or_x, y, s, size, color=INK, center=False, group=None):
        lines = s.split("\n")
        w = max(text_width(line, size) for line in lines)
        x = cx_or_x - w / 2 if center else cx_or_x
        return self._base("text", x, y, w, len(lines) * size * 1.25, strokeColor=color, text=s, originalText=s,
                          fontSize=size, fontFamily=2, textAlign="center" if center else "left",
                          verticalAlign="top", baseline=int(size * 0.9), containerId=None, autoResize=True,
                          lineHeight=1.25, groupIds=group or [])

    def image(self, svg, x, y, w, h, group=None):
        file_id = hashlib.sha1(svg.encode()).hexdigest()
        self.files[file_id] = {"mimeType": "image/svg+xml", "id": file_id, "created": 1, "lastRetrieved": 1,
                               "dataURL": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()}
        self._base("image", x, y, w, h, strokeColor="transparent", fileId=file_id, status="saved",
                   scale=[1, 1], crop=None, groupIds=group or [])

    def symbol(self, x, y, size):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><g fill="{INK}">{SYMBOL}</g></svg>'
        self.image(svg, x, y, size, size)

    def add(self, sec, oy):
        self.symbol(0, oy, 34)
        self.text(46, oy, sec.title, 28)
        ids = {}
        for key, b in sec.boxes.items():
            k = KINDS[b["kind"]]
            group = [f"{sec.key}-{key}"]
            rect = self._base("rectangle", b["x"], oy + b["y"], b["w"], b["h"], id=f"{sec.key}-{key}",
                              backgroundColor=k["fill"], strokeColor=k["stroke"], strokeWidth=1,
                              strokeStyle="dashed" if k["dashed"] else "solid", roundness={"type": 3},
                              groupIds=group)
            ids[key] = rect
            cx = b["x"] + b["w"] / 2
            self._base("rectangle", cx - 19, oy + b["y"] + 10, 38, 38, backgroundColor=k["cell"],
                       strokeColor=k["cell"], strokeWidth=1, roundness={"type": 3}, groupIds=group)
            self.image(icon_svg(b["icon"], k["glyph"]), cx - 12, oy + b["y"] + 17, 24, 24, group)
            self.text(cx, oy + b["y"] + 56, b["title"], 18, k["title"], center=True, group=group)
            self.text(cx, oy + b["y"] + 80, b["sub"], 14, k["sub"], center=True, group=group)
        for a in sec.arrows:
            pts = [(x, y + oy) for x, y in a["pts"]]
            x0, y0 = pts[0]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            e = self._base("arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), strokeColor=a["color"],
                           strokeStyle="dashed" if a["dashed"] else "solid",
                           points=[[x - x0, y - y0] for x, y in pts],
                           startBinding={"elementId": ids[a["a"]]["id"], "focus": 0, "gap": 2},
                           endBinding={"elementId": ids[a["b"]]["id"], "focus": 0, "gap": 2},
                           startArrowhead=None, endArrowhead="arrow", lastCommittedPoint=None, elbowed=False)
            ids[a["a"]]["boundElements"].append({"type": "arrow", "id": e["id"]})
            ids[a["b"]]["boundElements"].append({"type": "arrow", "id": e["id"]})
            if a["label"]:
                lx, ly = a["label_at"]
                self.text(lx, oy + ly - 12, a["label"], 13, GRAPHITE, center=a["anchor"] == "middle")
        for n in sec.notes:
            self.text(n["x"], oy + n["y"], n["text"], n["size"], n["color"])


def main():
    SVG_DIR.mkdir(exist_ok=True)
    doc = Excalidraw()
    logo = LOGO.read_text(encoding="utf-8")
    doc.image(logo, 0, -150, 268, 60)  # horizontal lockup, 893.6 x 200
    doc.text(0, -70, "Ask your data in plain language. Get SQL, tables and charts back.", 20, GRAPHITE)
    oy = 0
    for sec in SECTIONS:
        (SVG_DIR / f"{sec.key}.svg").write_text(svg_section(sec), encoding="utf-8")
        doc.add(sec, oy)
        oy += sec.height + 120
    data = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com", "elements": doc.elements,
            "appState": {"viewBackgroundColor": CANVAS, "gridSize": None}, "files": doc.files}
    EXCALIDRAW.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(doc.elements)} elements, {len(SECTIONS)} SVG sections")


if __name__ == "__main__":
    main()
