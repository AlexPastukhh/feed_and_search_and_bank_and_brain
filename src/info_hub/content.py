"""Pure chunking with stable character offsets into the original text."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    char_start: int
    char_end: int
    text: str


def split_text(
    text: str, *, max_chars: int = 1400, overlap: int = 160,
) -> list[TextChunk]:
    if max_chars < 100 or not 0 <= overlap < max_chars // 2:
        raise ValueError("Invalid chunk sizing")
    result: list[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            word_end = text.rfind(" ", start + max_chars // 2, end)
            if word_end > start:
                end = word_end + 1
        result.append(TextChunk(
            ordinal=len(result),
            char_start=start,
            char_end=end,
            text=text[start:end],
        ))
        if end == len(text):
            break
        start = end - overlap
    return result
