from .claude import ClaudeSource
from .codex import CodexSource
from .devin import DevinSource

DEFAULT_SOURCES = [
    CodexSource(),
    ClaudeSource(),
    DevinSource(),
]
