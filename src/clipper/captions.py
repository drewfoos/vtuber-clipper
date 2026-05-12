from dataclasses import dataclass, field

from clipper.util.timing import seconds_to_srt

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
    "Bold, Outline, Shadow, Alignment, MarginV"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


def _ass_time(seconds: float) -> str:
    """ASS uses H:MM:SS.cs (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


@dataclass
class AssBuilder:
    """Accumulates ASS styles and dialogue events; renders to a complete .ass document.

    Used by `generate_basic_ass` here and by every Plan B effect that emits ASS layers
    (emoji_burst, hook_card, etc.). Compose them by passing one AssBuilder around.
    """
    width: int
    height: int
    style_lines: list[str] = field(default_factory=list)
    event_lines: list[str] = field(default_factory=list)

    def add_style(
        self,
        name: str = "Default",
        fontname: str = "Arial Black",
        fontsize: int = 72,
        primary: str = "&H00FFFFFF",
        outline: str = "&H00000000",
        bold: int = 1,
        outline_width: int = 4,
        margin_v: int = 300,
        alignment: int = 2,
    ) -> None:
        self.style_lines.append(
            f"Style: {name},{fontname},{fontsize},{primary},{outline},&H00000000,"
            f"{bold},{outline_width},0,{alignment},{margin_v}"
        )

    def add_dialogue(
        self,
        start: float,
        end: float,
        text: str,
        style: str = "Default",
        layer: int = 0,
        margin_l: int = 0,
        margin_r: int = 0,
        margin_v: int = 0,
        effect: str = "",
    ) -> None:
        self.event_lines.append(
            f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,"
            f"{margin_l},{margin_r},{margin_v},{effect},{text}"
        )

    def render(self) -> str:
        if not self.style_lines:
            self.add_style()
        sections = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {self.width}",
            f"PlayResY: {self.height}",
            "",
            "[V4+ Styles]",
            _STYLE_FORMAT,
            *self.style_lines,
            "",
            "[Events]",
            _EVENT_FORMAT,
            *self.event_lines,
            "",
        ]
        return "\n".join(sections)


def generate_srt(words: list[dict], clip_start: float, max_words_per_cue: int = 3) -> str:
    cues = []
    for i in range(0, len(words), max_words_per_cue):
        group = words[i : i + max_words_per_cue]
        start = group[0]["start"] - clip_start
        end = group[-1]["end"] - clip_start
        text = " ".join(w["word"] for w in group)
        idx = len(cues) + 1
        cues.append(
            f"{idx}\n{seconds_to_srt(start)} --> {seconds_to_srt(end)}\n{text}\n"
        )
    return "\n".join(cues)


def generate_basic_ass(
    words: list[dict],
    clip_start: float,
    output_size: tuple[int, int],
    max_words_per_cue: int = 3,
) -> str:
    builder = AssBuilder(width=output_size[0], height=output_size[1])
    for i in range(0, len(words), max_words_per_cue):
        group = words[i : i + max_words_per_cue]
        start = group[0]["start"] - clip_start
        end = group[-1]["end"] - clip_start
        text = " ".join(g["word"] for g in group)
        builder.add_dialogue(start, end, text)
    return builder.render()


def generate_window3_ass(
    words: list[dict],
    clip_start: float,
    output_size: tuple[int, int],
) -> str:
    """3-word sliding window with the active word highlighted yellow + slight scale.

    Emits one Dialogue line per word. Each line spans that word's [start, end)
    in clip-local time and renders three words (prev, active, next) with the
    active word in yellow at 1.12x scale.
    """
    builder = AssBuilder(width=output_size[0], height=output_size[1])

    yellow = "&H0000FFFF&"   # ASS BGR: FF FF 00 = yellow
    white = "&H00FFFFFF&"

    for idx, w in enumerate(words):
        start = w["start"] - clip_start
        end = w["end"] - clip_start
        prev = words[idx - 1]["word"] if idx > 0 else ""
        nxt = words[idx + 1]["word"] if idx + 1 < len(words) else ""

        parts = []
        if prev:
            parts.append(f"{{\\1c{white}}}{prev}")
        parts.append(f"{{\\1c{yellow}\\fscx112\\fscy112}}{w['word']}{{\\1c{white}\\fscx100\\fscy100}}")
        if nxt:
            parts.append(nxt)
        text = "{\\fad(80,0)}" + " ".join(parts)
        builder.add_dialogue(start, end, text)

    return builder.render()


def generate_ass(
    style: str,
    words: list[dict],
    clip_start: float,
    output_size: tuple[int, int],
) -> str:
    """Dispatch by style name. Falls back to 'basic' for unknown styles."""
    if style == "window3":
        return generate_window3_ass(words, clip_start, output_size)
    return generate_basic_ass(words, clip_start, output_size)
