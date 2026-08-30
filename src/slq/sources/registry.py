from .claude import ClaudeSource
from .codex import CodexSource
from .cursor import CursorSource
from .devin import DevinSource

DEFAULT_SOURCES = [
    CodexSource(),
    ClaudeSource(),
    CursorSource(),
    DevinSource(),
]
