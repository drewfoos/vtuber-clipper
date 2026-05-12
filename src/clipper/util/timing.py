def seconds_to_hms(seconds: float) -> str:
    """1234.567 -> '00:20:34.567'"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def seconds_to_srt(seconds: float) -> str:
    """SRT uses comma decimal: '00:20:34,567'"""
    return seconds_to_hms(seconds).replace(".", ",")

def hms_to_seconds(hms: str) -> float:
    """'00:20:34.567' -> 1234.567"""
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
