"""Product artwork drawn in code (inline SVG). No image files, no hosting, no licences.

Each product maps to a packaging shape plus colours. Everything interpolated into
the SVG is either a fixed value from this file or passed through `escape`, so a
product name can never become markup.
"""

from __future__ import annotations

from html import escape

# product id -> (shape, main colour, accent colour, label text)
ART: dict[str, tuple[str, str, str, str]] = {
    "p1": ("sack", "#e9dcc0", "#9a7b3f", "RICE"),
    "p2": ("bag", "#f3e3b3", "#c28a1d", "SEMO"),
    "p3": ("sack", "#f1e6c9", "#8c6a2f", "GARRI"),
    "p4": ("bag", "#d9b99b", "#7a4a2a", "BEANS"),
    "p5": ("bottle", "#d9531e", "#8a2b0c", "PALM OIL"),
    "p6": ("bottle", "#f2c94c", "#a8791a", "GROUNDNUT"),
    "p7": ("pack", "#e4572e", "#ffc107", "NOODLES"),
    "p8": ("bag", "#f2c94c", "#7a9a2f", "PLANTAIN"),
    "p9": ("tub", "#e8b75a", "#9a5a1a", "CHIN CHIN"),
    "p10": ("pie", "#d99a4a", "#8a5a22", "MEAT PIE"),
    "p11": ("can", "#e8f1fb", "#1f5fa8", "MILK"),
    "p12": ("bottle", "#cfe8f7", "#2f86c0", "WATER"),
    "p13": ("can", "#d62828", "#ffffff", "COLA"),
    "p14": ("bottle", "#f7f0ff", "#8f5fc0", "YOGHURT"),
    "p15": ("tomato", "#d93a2b", "#3f7d2f", ""),
    "p16": ("onion", "#c97b4a", "#6f8f3a", ""),
    "p17": ("yam", "#a9794a", "#6b4426", ""),
    "p18": ("pepper", "#d12a1f", "#3f7d2f", ""),
    "p19": ("bottle", "#4ec3a1", "#1f7d63", "DISH SOAP"),
    "p20": ("rolls", "#f4f4f4", "#9aa5ad", ""),
    "p21": ("box", "#3d7bd9", "#ffffff", "DETERGENT"),
    "p22": ("can", "#6fae3f", "#2f5a1a", "INSECT"),
    "p23": ("loaf", "#d9a35a", "#8a5a22", ""),
    "p24": ("can", "#1a1a1a", "#f2c94c", "ENERGY"),
    "p25": ("can", "#1f4fa8", "#d62828", "COLA"),
    "p26": ("bottle", "#5a3a1a", "#c28a1d", "MALT"),
    "p27": ("bottle", "#f5e3ef", "#c0557f", "MILKY"),
    "p28": ("perfume", "#e9c3e0", "#8f3a7a", ""),
}

DEFAULT = ("box", "#e8efe4", "#2f5a41", "")


def _label(text: str, cx: int, cy: int, fill: str, size: int = 11) -> str:
    if not text:
        return ""
    return (
        f'<text x="{cx}" y="{cy}" text-anchor="middle" font-family="Arial,sans-serif" '
        f'font-weight="700" font-size="{size}" fill="{fill}">{escape(text)}</text>'
    )


def _shape(shape: str, main: str, accent: str, text: str) -> str:
    if shape == "bottle":
        return (
            f'<rect x="52" y="14" width="36" height="16" rx="4" fill="{accent}"/>'
            f'<path d="M56 30h28v14c14 6 20 16 20 30v54c0 8-6 14-14 14H50c-8 0-14-6-14-14V74c0-14 6-24 20-30z" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<rect x="38" y="84" width="64" height="34" fill="{accent}" opacity=".9"/>'
            + _label(text, 70, 106, "#fff", 9)
        )
    if shape == "can":
        return (
            f'<rect x="38" y="20" width="64" height="12" rx="5" fill="{accent}"/>'
            f'<rect x="38" y="28" width="64" height="104" rx="8" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<rect x="38" y="62" width="64" height="38" fill="{accent}" opacity=".85"/>'
            + _label(text, 70, 86, main if main != "#ffffff" else accent, 11)
        )
    if shape in ("bag", "sack"):
        top = "M34 30h72l8 14-8 8H34l-8-8z" if shape == "bag" else "M44 22h52l10 18-6 10H40l-6-10z"
        return (
            f'<path d="{top}" fill="{accent}" opacity=".8"/>'
            f'<path d="M30 50h80l6 80c0 6-5 10-10 10H34c-5 0-10-4-10-10z" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<rect x="36" y="76" width="68" height="30" rx="4" fill="#fff" opacity=".85"/>'
            + _label(text, 70, 96, accent, 12)
        )
    if shape == "pack":
        return (
            f'<rect x="22" y="42" width="96" height="68" rx="8" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<path d="M22 56h96" stroke="{accent}" stroke-width="4"/>'
            f'<path d="M26 44l8-6h4l-4 6zm16 0l8-6h4l-4 6zm16 0l8-6h4l-4 6zm16 0l8-6h4l-4 6zm16 0l8-6h4l-4 6z" fill="{accent}"/>'
            + _label(text, 70, 88, "#fff", 12)
        )
    if shape == "tub":
        return (
            f'<rect x="30" y="34" width="80" height="14" rx="6" fill="{accent}"/>'
            f'<path d="M34 48h72l-6 78c0 6-4 10-10 10H50c-6 0-10-4-10-10z" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<rect x="42" y="74" width="56" height="26" rx="4" fill="#fff" opacity=".85"/>'
            + _label(text, 70, 91, accent, 10)
        )
    if shape == "pie":
        return (
            f'<ellipse cx="70" cy="96" rx="52" ry="26" fill="{accent}" opacity=".35"/>'
            f'<path d="M20 92c0-30 22-48 50-48s50 18 50 48z" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<path d="M40 70l8 6m8-10l8 6m8-8l8 6" stroke="{accent}" stroke-width="3" stroke-linecap="round"/>'
        )
    if shape == "loaf":
        return (
            f'<path d="M18 92c-4-30 14-52 52-52s56 22 52 52c0 8-6 14-14 14H32c-8 0-14-6-14-14z" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<path d="M44 58l10 22m10-26l10 26m10-22l10 22" stroke="{accent}" stroke-width="3" stroke-linecap="round" fill="none"/>'
        )
    if shape == "tomato":
        return (
            f'<circle cx="70" cy="86" r="40" fill="{main}"/>'
            f'<path d="M52 52l18 10 18-10-8 14-10 2-10-2z" fill="{accent}"/>'
            f'<ellipse cx="56" cy="76" rx="8" ry="12" fill="#fff" opacity=".25"/>'
        )
    if shape == "onion":
        return (
            f'<path d="M70 38c-6 14-38 22-38 52 0 22 18 34 38 34s38-12 38-34c0-30-32-38-38-52z" fill="{main}"/>'
            f'<path d="M70 38c-2 20-12 50-12 84M70 38c2 20 12 50 12 84" stroke="{accent}" stroke-width="2.5" fill="none" opacity=".6"/>'
            f'<path d="M70 38l-4-14m4 14l4-14" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>'
        )
    if shape == "yam":
        return (
            f'<path d="M26 104c-8-22 6-44 34-52 28-8 56 0 62 22 6 20-14 40-48 44-24 2-42-2-48-14z" fill="{main}"/>'
            f'<path d="M44 80l6 6m14-14l6 6m14-6l6 6m-52 22l6 6m24-8l6 6" stroke="{accent}" stroke-width="3" stroke-linecap="round"/>'
        )
    if shape == "pepper":
        return (
            f'<path d="M40 56c20-12 50-6 60 16 8 18-2 46-30 56-14-18-18-44-30-72z" fill="{main}"/>'
            f'<path d="M96 54c4-12 12-18 18-20" stroke="{accent}" stroke-width="5" stroke-linecap="round" fill="none"/>'
            f'<ellipse cx="62" cy="78" rx="5" ry="12" fill="#fff" opacity=".25"/>'
        )
    if shape == "rolls":
        roll = lambda x: (  # noqa: E731
            f'<rect x="{x}" y="58" width="40" height="64" rx="8" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<ellipse cx="{x + 20}" cy="58" rx="20" ry="8" fill="#fff" stroke="{accent}" stroke-width="3"/>'
            f'<ellipse cx="{x + 20}" cy="58" rx="7" ry="3" fill="{accent}" opacity=".5"/>'
        )
        return roll(20) + roll(80)
    if shape == "perfume":
        return (
            f'<rect x="58" y="20" width="24" height="18" rx="3" fill="{accent}"/>'
            f'<rect x="62" y="38" width="16" height="10" fill="{accent}" opacity=".7"/>'
            f'<rect x="32" y="48" width="76" height="82" rx="14" fill="{main}" stroke="{accent}" stroke-width="3"/>'
            f'<ellipse cx="54" cy="76" rx="6" ry="16" fill="#fff" opacity=".4"/>'
        )
    # box (default, detergent)
    return (
        f'<rect x="30" y="34" width="80" height="100" rx="6" fill="{main}" stroke="{accent}" stroke-width="3"/>'
        f'<rect x="30" y="34" width="80" height="18" rx="6" fill="{accent}" opacity=".85"/>'
        f'<rect x="40" y="74" width="60" height="30" rx="4" fill="#fff" opacity=".9"/>'
        + _label(text, 70, 94, accent, 10)
    )


def svg_for(product_id: str, name: str) -> str:
    """Return a complete <svg> for a product. `name` is only used as the accessible label."""
    shape, main, accent, text = ART.get(product_id, DEFAULT)
    return (
        f'<svg class="art" viewBox="0 0 140 150" role="img" aria-label="{escape(name, quote=True)}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<ellipse cx="70" cy="140" rx="42" ry="6" fill="#000" opacity=".12"/>'
        f"{_shape(shape, main, accent, text)}</svg>"
    )
