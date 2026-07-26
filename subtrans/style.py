"""
Subtitle appearance settings (PRD 九 字幕样式).

Kept separate from rendering so the preview and the exporter share exactly one
definition, and so restyling only re-renders — it never re-runs OCR or DeepL.
"""

from __future__ import annotations

from dataclasses import dataclass


def _ass_colour(hex_rgb: str, alpha: int = 0) -> str:
    """``#RRGGBB`` -> ASS ``&HAABBGGRR``. ``alpha`` 0=opaque, 255=transparent."""
    s = hex_rgb.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        s = "FFFFFF"
    r, g, b = s[0:2], s[2:4], s[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


# Background box behind the caption.
BG_NONE = "none"              # outline only
BG_BLACK = "black"            # opaque box
BG_SEMI = "semi"              # semi-transparent box

# Where the caption is drawn.
POS_ORIGINAL = "original"     # exactly where the source caption was
POS_TOP = "top"
POS_BOTTOM = "bottom"


@dataclass
class SubtitleStyle:
    font: str = "Arial"
    font_size: int = 0             # 0 = auto (scaled to the frame / source box)
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 2
    shadow: int = 1                # 0 = off
    background: str = BG_NONE      # none | black | semi
    position: str = POS_ORIGINAL   # original | top | bottom
    bold: bool = True
    margin_v: int = 28             # used by top/bottom positioning

    # -- derived values used by the ASS writer ------------------------------
    @property
    def primary_ass(self) -> str:
        return _ass_colour(self.color)

    @property
    def outline_ass(self) -> str:
        return _ass_colour(self.outline_color)

    @property
    def back_ass(self) -> str:
        if self.background == BG_BLACK:
            return _ass_colour("#000000", 0)
        if self.background == BG_SEMI:
            return _ass_colour("#000000", 0x80)
        return _ass_colour("#000000", 0)

    @property
    def border_style(self) -> int:
        """ASS BorderStyle: 3 draws an opaque/semi box, 1 draws an outline."""
        return 3 if self.background in (BG_BLACK, BG_SEMI) else 1

    @property
    def alignment(self) -> int:
        """ASS numpad alignment used when not pinned to the source box."""
        if self.position == POS_TOP:
            return 8               # top-centre
        return 2                   # bottom-centre

    def resolved_font_size(self, frame_height: int) -> int:
        return self.font_size or max(18, int(frame_height * 0.062))
