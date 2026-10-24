"""Function-call policy: built-in deny list, optional allowlist mode, and UDF handling."""

from __future__ import annotations

from collections.abc import Iterator

from sqlguard_ninja.core.findings import Action, Category, Finding, Severity
from sqlguard_ninja.core.rules.base import RuleContext

# Grouped so that a finding can say *why* a function is dangerous.
DENIED_FUNCTIONS: dict[str, frozenset[str]] = {
    "file_or_program_access": frozenset(
        {
            "pg_read_file",
            "pg_read_binary_file",
            "pg_ls_dir",
            "pg_stat_file",
            "pg_ls_logdir",
            "pg_ls_waldir",
            "pg_ls_tmpdir",
            "pg_ls_archive_statusdir",
            "lo_import",
            "lo_export",
            "lo_get",
            "lo_put",
            "lo_create",
            "lo_unlink",
            "lo_from_bytea",
            "readfile",
            "writefile",
            "edit",
            "load_extension",
            "fts3_tokenizer",
        }
    ),
    "remote_or_dynamic_sql": frozenset(
        {
            "dblink",
            "dblink_exec",
            "dblink_connect",
            "dblink_connect_u",
            "dblink_open",
            "dblink_send_query",
            "query_to_xml",
            "query_to_xml_and_xmlschema",
            "query_to_xmlschema",
            "cursor_to_xml",
            "table_to_xml",
            "table_to_xml_and_xmlschema",
            "schema_to_xml",
            "database_to_xml",
            "database_to_xml_and_xmlschema",
        }
    ),
    "denial_of_service": frozenset(
        {
            "pg_sleep",
            "pg_sleep_for",
            "pg_sleep_until",
            "pg_advisory_lock",
            "pg_advisory_xact_lock",
            "pg_advisory_lock_shared",
            "pg_try_advisory_lock",
            "randomblob",
            "zeroblob",
        }
    ),
    "administration_or_state_change": frozenset(
        {
            "pg_terminate_backend",
            "pg_cancel_backend",
            "pg_reload_conf",
            "pg_rotate_logfile",
            "set_config",
            "pg_switch_wal",
            "pg_create_restore_point",
            "pg_promote",
            "pg_logical_emit_message",
            "pg_notify",
            "nextval",
            "setval",
            "txid_current",
            "pg_current_xact_id",
        }
    ),
}

RECONNAISSANCE_FUNCTIONS = frozenset(
    {
        "version",
        "current_version",
        "current_setting",
        "inet_server_addr",
        "inet_server_port",
        "inet_client_addr",
        "pg_postmaster_start_time",
        "pg_backend_pid",
        "pg_has_role",
        "has_table_privilege",
        "has_column_privilege",
        "has_schema_privilege",
        "has_database_privilege",
        "has_function_privilege",
        "sqlite_version",
        "sqlite_source_id",
        "sqlite_compileoption_used",
        "sqlite_compileoption_get",
    }
)

DENIED_PREFIXES = ("dblink", "lo_")
REVIEW_PREFIXES = ("pg_",)

_ALL_DENIED = frozenset().union(*DENIED_FUNCTIONS.values())


def _deny_group(name: str) -> str | None:
    for group, names in DENIED_FUNCTIONS.items():
        if name in names:
            return group
    if name.startswith(DENIED_PREFIXES):
        return "file_or_program_access"
    return None


class FunctionPolicyRule:
    """Apply the policy's function rules to every function call in the query."""

    rule_ids = (
        "function.denied",
        "function.not_allowlisted",
        "function.review",
        "function.unknown",
    )

    def check(self, ctx: RuleContext) -> Iterator[Finding]:
        fp = ctx.policy.functions
        extra_deny = set(fp.deny)
        exceptions = set(fp.allow)
        review = set(fp.review)
        seen: set[str] = set()
        for func in ctx.analysis.functions:
            if func.display in seen:
                continue
            seen.add(func.display)
            names = func.names
            shown = ctx.name("function", func.display)

            if fp.mode == "allowlist":
                if not names & exceptions:
                    yield Finding(
                        rule_id="function.not_allowlisted",
                        category=Category.FUNCTION,
                        severity=Severity.MEDIUM,
                        action=Action.DENY,
                        message=f"The {shown} is not on the approved function list.",
                    )
                    continue
            elif names & exceptions:
                continue

            group = next((g for n in names if (g := _deny_group(n))), None)
            if names & extra_deny or (group is not None and fp.mode == "denylist"):
                yield Finding(
                    rule_id="function.denied",
                    category=Category.FUNCTION,
                    severity=Severity.CRITICAL,
                    action=Action.DENY,
                    message=f"The {shown} is not permitted.",
                    detail=f"group={group or 'policy_deny'}",
                    metadata={"group": group or "policy_deny"},
                )
                continue
            if fp.mode == "allowlist":
                continue
            if names & review or names & RECONNAISSANCE_FUNCTIONS:
                yield Finding(
                    rule_id="function.review",
                    category=Category.FUNCTION,
                    severity=Severity.MEDIUM,
                    action=Action.REVIEW,
                    message=f"The {shown} reveals server or privilege details and needs review.",
                )
                continue
            if not func.known:
                if any(n.startswith(REVIEW_PREFIXES) for n in names):
                    action = Action.REVIEW
                else:
                    action = fp.unknown_function_action
                yield Finding(
                    rule_id="function.unknown",
                    category=Category.FUNCTION,
                    severity=Severity.LOW,
                    action=action,
                    message=f"The {shown} is not a recognised built-in function.",
                    detail="may be a user-defined function; consider functions.mode=allowlist",
                )
