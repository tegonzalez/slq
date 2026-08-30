from ..pushdown import SQLBuilder, SQLColumn

EVENT_KINDS = ("user", "agent", "thinking", "tool_call", "tool_output", "meta", "other")

_BUBBLE_COMPOSER = "substr(k.key, 10, instr(substr(k.key, 10), ':') - 1)"
_BUBBLE_ID = (
    "COALESCE(json_extract(k.value, '$.bubbleId'), "
    f"substr(k.key, length({_BUBBLE_COMPOSER}) + 11))"
)
_BUBBLE_TYPE = "json_extract(k.value, '$.type')"
_WORKSPACE = "COALESCE(json_extract(h.value, '$.workspaceIdentifier.uri.fsPath'), '')"

_TIMESTAMP = (
    "CASE "
    f"WHEN typeof(json_extract(k.value, '$.createdAt')) IN ('integer', 'real') "
    "THEN COALESCE(strftime('%Y-%m-%d %H:%M:%S', "
    "json_extract(k.value, '$.createdAt') / 1000.0, 'unixepoch'), '') "
    "ELSE COALESCE(strftime('%Y-%m-%d %H:%M:%S', "
    "datetime(json_extract(k.value, '$.createdAt'))), '') "
    "END"
)

_KIND = (
    f"CASE {_BUBBLE_TYPE} "
    "WHEN 1 THEN 'user' WHEN 2 THEN 'agent' ELSE 'other' END"
)

_ROLE = (
    f"CASE {_BUBBLE_TYPE} "
    "WHEN 1 THEN 'user' WHEN 2 THEN 'assistant' ELSE 'other' END"
)


def columns() -> SQLBuilder:
    """Return the SQL column mapping for the Cursor event query."""
    return SQLBuilder(
        {
            "tool": SQLColumn("'cursor'"),
            "session_id": SQLColumn(_BUBBLE_COMPOSER),
            "record_id": SQLColumn(_BUBBLE_ID),
            "parent_id": SQLColumn("''"),
            "timestamp": SQLColumn(_TIMESTAMP),
            "end_timestamp": SQLColumn("''"),
            "kind": SQLColumn(_KIND),
            "role": SQLColumn(_ROLE),
            "rec_type": SQLColumn("'bubble'"),
            "subtype": SQLColumn("COALESCE(json_extract(h.value, '$.unifiedMode'), '')"),
            "content": SQLColumn("COALESCE(json_extract(k.value, '$.text'), '')"),
            "cwd": SQLColumn(_WORKSPACE),
            "project": SQLColumn(_WORKSPACE),
            "model": SQLColumn("COALESCE(json_extract(k.value, '$.modelType'), '')"),
            "record_count": SQLColumn("''"),
            "duration": SQLColumn(
                "COALESCE(CAST(CAST(json_extract(k.value, '$.turnDurationMs') "
                "AS REAL) / 1000.0 AS TEXT), '')"
            ),
        }
    )


def event_query(where: str) -> str:
    """Return the one joined Cursor event query for a store.

    The query bounds the ``cursorDiskKV`` key range so all bubble records for
    every composer come from a single statement.  The caller supplies the
    pushdown ``where`` clause and its parameters.
    """
    return (
        "SELECT k.key, k.value, h.value AS header_value "
        "FROM cursorDiskKV k "
        "LEFT JOIN composerHeaders h "
        f"ON h.composerId = {_BUBBLE_COMPOSER} "
        "WHERE k.key >= 'bubbleId:' AND k.key < 'bubbleId;' "
        f"AND ({where}) "
        f"ORDER BY {_TIMESTAMP}, k.key"
    )


def session_query() -> str:
    """Return the one Cursor session query for a store."""
    return (
        "SELECT h.*, "
        "(SELECT COUNT(*) FROM cursorDiskKV k "
        "WHERE k.key >= 'bubbleId:' || h.composerId || ':' "
        "AND k.key < 'bubbleId:' || h.composerId || ';') AS record_count "
        "FROM composerHeaders h ORDER BY h.createdAt, h.composerId"
    )
