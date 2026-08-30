"""Render a local, looping architecture walkthrough GIF for Meridian's demo."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "meridian-architecture-walkthrough.gif"
WIDTH, HEIGHT = 1600, 940

NAVY = "#102A43"
TEAL = "#0F766E"
TEAL_LIGHT = "#CCFBF1"
PURPLE = "#7C3AED"
PURPLE_LIGHT = "#EDE9FE"
AMBER = "#D97706"
AMBER_LIGHT = "#FEF3C7"
BLUE = "#2563EB"
BLUE_LIGHT = "#DBEAFE"
SLATE = "#64748B"
SLATE_LIGHT = "#F1F5F9"
WHITE = "#FFFFFF"
GREEN = "#16A34A"
GREEN_LIGHT = "#DCFCE7"

FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

NODES = {
    "intake": (90, 220, 345, 330, "Analyst selects\nan alert", BLUE_LIGHT, BLUE),
    "orchestrator": (
        465,
        220,
        810,
        330,
        "LangGraph coordinator\n(A2A-style typed handoffs)",
        TEAL_LIGHT,
        TEAL,
    ),
    "evidence_agent": (90, 405, 345, 515, "Evidence\nAgent", TEAL_LIGHT, TEAL),
    "mcp": (465, 405, 720, 515, "Read-only MCP\nevidence gateway", PURPLE_LIGHT, PURPLE),
    "data": (840, 405, 1095, 515, "Synthetic alerts,\naccounts + transactions", SLATE_LIGHT, SLATE),
    "policy_agent": (90, 575, 345, 685, "Policy Retrieval\nAgent", TEAL_LIGHT, TEAL),
    "rag": (465, 575, 720, 685, "Hybrid RAG +\ncross-encoder reranker", PURPLE_LIGHT, PURPLE),
    "answerability": (840, 575, 1095, 685, "Answerability\ngate", AMBER_LIGHT, AMBER),
    "synthesis_agent": (90, 745, 345, 855, "Synthesis\nAgent", TEAL_LIGHT, TEAL),
    "draft": (465, 745, 720, 855, "Structured\nreview brief", TEAL_LIGHT, TEAL),
    "safety": (840, 745, 1095, 855, "Grounding +\nsafety gates", AMBER_LIGHT, AMBER),
    "human": (1215, 745, 1510, 855, "Human analyst\ndecision", GREEN_LIGHT, GREEN),
    "observability": (
        1215,
        405,
        1510,
        685,
        "Checkpoints\nLangSmith traces\nPrometheus metrics\nFeedback + evals",
        SLATE_LIGHT,
        SLATE,
    ),
}

STEPS = [
    ("intake", "1. An analyst selects a synthetic payment-scam alert."),
    ("orchestrator", "2. LangGraph coordinates bounded roles through typed A2A-style handoffs."),
    ("evidence_agent", "3. The Evidence Agent gathers only read-only case evidence through MCP."),
    ("policy_agent", "4. The Policy Retrieval Agent runs hybrid RAG and cross-encoder reranking."),
    ("answerability", "5. The answerability gate stops weak policy context before generation."),
    (
        "synthesis_agent",
        "6. The Synthesis Agent creates a structured, evidence-backed review brief.",
    ),
    ("safety", "7. Grounding, PII, citation and action gates validate the draft."),
    ("human", "8. The human analyst decides; observability, feedback and evals close the loop."),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def centre_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str) -> None:
    x1, y1, x2, y2 = box
    lines = text.splitlines()
    line_height = 27
    total_height = line_height * len(lines)
    y = (y1 + y2 - total_height) // 2
    for line in lines:
        bounds = draw.textbbox((0, 0), line, font=font(20, bold=True))
        draw.text(
            ((x1 + x2 - (bounds[2] - bounds[0])) // 2, y), line, fill=NAVY, font=font(20, bold=True)
        )
        y += line_height


def arrow(
    draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], active: bool = False
) -> None:
    colour = TEAL if active else "#94A3B8"
    width = 7 if active else 4
    draw.line([start, end], fill=colour, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        points = [(x2, y2), (x2 - 18 * direction, y2 - 10), (x2 - 18 * direction, y2 + 10)]
    else:
        direction = 1 if y2 > y1 else -1
        points = [(x2, y2), (x2 - 10, y2 - 18 * direction), (x2 + 10, y2 - 18 * direction)]
    draw.polygon(points, fill=colour)


def draw_frame(active: str, step_text: str, final_frame: bool = False) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#F8FAFC")
    draw = ImageDraw.Draw(image)
    draw.text(
        (70, 48), "Meridian — Payment Scam Review Copilot", fill=NAVY, font=font(42, bold=True)
    )
    draw.text((72, 105), "High-level governed investigation workflow", fill=SLATE, font=font(24))

    for name, node in NODES.items():
        x1, y1, x2, y2, label, fill, outline = node
        selected = name == active or final_frame
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=18,
            fill=fill if selected else WHITE,
            outline=outline if selected else "#CBD5E1",
            width=6 if selected else 3,
        )
        centre_text(draw, (x1, y1, x2, y2), label)

    arrows = [
        ("intake", "orchestrator", (345, 275), (465, 275)),
        ("orchestrator", "evidence_agent", (565, 330), (220, 405)),
        ("evidence_agent", "mcp", (345, 460), (465, 460)),
        ("mcp", "data", (720, 460), (840, 460)),
        ("evidence_agent", "policy_agent", (220, 515), (220, 575)),
        ("policy_agent", "rag", (345, 630), (465, 630)),
        ("rag", "answerability", (720, 630), (840, 630)),
        ("policy_agent", "synthesis_agent", (220, 685), (220, 745)),
        ("answerability", "synthesis_agent", (840, 665), (345, 785)),
        ("synthesis_agent", "draft", (345, 800), (465, 800)),
        ("draft", "safety", (720, 800), (840, 800)),
        ("safety", "human", (1095, 800), (1215, 800)),
        ("orchestrator", "observability", (810, 275), (1215, 465)),
        ("human", "observability", (1360, 745), (1360, 685)),
    ]
    for source, target, start, end in arrows:
        arrow(draw, start, end, active in {source, target} or final_frame)

    draw.rounded_rectangle((70, 875, 1530, 920), radius=12, fill=NAVY)
    draw.text((95, 885), step_text, fill=WHITE, font=font(20, bold=True))
    return image


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [draw_frame(node, text) for node, text in STEPS]
    frames.append(
        draw_frame(
            "human", "All decisions and consequential actions remain with the human analyst.", True
        )
    )
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=[1450] * len(frames),
        loop=0,
        optimize=False,
        disposal=2,
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
