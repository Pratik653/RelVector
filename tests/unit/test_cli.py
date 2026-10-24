from __future__ import annotations

import json

import pytest

from sqlguard_ninja.cli.main import main
from tests.conftest import DATASET_PATH, POLICY_PATH

P = str(POLICY_PATH)


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "sqlninja" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT o.id FROM orders o WHERE o.tenant_id = 1", 0),
        ("SELECT o.id FROM orders o", 1),
        ("SELECT p.iban FROM payments p", 3),
    ],
)
def test_validate_exit_codes(capsys, sql, code):
    role = "platform_admin" if "iban" in sql else "support_analyst"
    rc, out, _ = run(
        capsys, "validate", "--policy", P, "--role", role, "--tenant", "1", "--sql", sql
    )
    assert rc == code
    assert out.split(":")[0] in {"ALLOW", "DENY", "REVIEW"}


def test_validate_json_and_context(capsys):
    rc, out, _ = run(
        capsys,
        "validate",
        "--policy",
        P,
        "--role",
        "support_analyst",
        "--context",
        '{"tenant_id": 1}',
        "--format",
        "json",
        "--sql",
        "SELECT o.id FROM orders o WHERE o.tenant_id = 1",
    )
    assert rc == 0 and json.loads(out)["decision"] == "allow"


def test_validate_file_and_stdin(capsys, tmp_path, monkeypatch):
    f = tmp_path / "q.sql"
    f.write_text("DROP TABLE orders")
    assert (
        run(capsys, "validate", "--policy", P, "--role", "support_analyst", "--file", str(f))[0]
        == 1
    )
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT 1"))
    assert run(capsys, "validate", "--policy", P, "--role", "support_analyst", "--stdin")[0] == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["validate", "--policy", P, "--role", "x"],  # no input
        ["validate", "--policy", P, "--sql", "x", "--context", "{bad"],
        ["validate", "--policy", P, "--sql", "x", "--context", "[1]"],
        ["validate", "--policy", "missing.yaml", "--sql", "x"],
        ["benchmark", "run", "--dataset", str(DATASET_PATH), "--adapter", "bogus"],
        ["benchmark", "run", "--dataset", str(DATASET_PATH), "--adapter", "external:nope"],
        ["benchmark", "run", "--dataset", str(DATASET_PATH), "--category", "no-such-category"],
        ["benchmark", "compare", "--baseline", "missing.json", "--candidate", "missing.json"],
    ],
)
def test_usage_errors_exit_2(capsys, argv):
    rc, _, err = run(capsys, *argv)
    assert rc == 2 and err.startswith("error:")


def test_policy_check_and_suggest(capsys):
    rc, out, _ = run(capsys, "policy", "check", "--policy", P)
    assert rc == 0 and "is valid" in out and "allowlist" in out
    rc, out, _ = run(capsys, "policy", "suggest", "--policy", P)
    assert rc == 0 and "Suggestions only" in out


def test_dataset_stats(capsys):
    rc, out, _ = run(capsys, "dataset", "stats", "--dataset", str(DATASET_PATH))
    assert rc == 0 and json.loads(out)["unique_cases"] >= 500


def test_init_benchmark_compare_flow(capsys, tmp_path, monkeypatch):
    project = tmp_path / "proj"
    assert run(capsys, "init", str(project))[0] == 0
    assert run(capsys, "init", str(project))[0] == 2  # refuses to overwrite
    cfg = str(project / "sqlninja.yaml")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc, out, _ = run(capsys, "benchmark", "run", "--config", cfg, "--summary")
    assert rc == 0 and "recall 1.0" in out
    assert "SQL security benchmark" in summary.read_text(encoding="utf-8")

    # Accepting a baseline is refused inside CI, allowed locally.
    monkeypatch.setenv("CI", "true")
    assert run(capsys, "benchmark", "baseline", "--config", cfg)[0] == 2
    monkeypatch.delenv("CI")
    assert run(capsys, "benchmark", "baseline", "--config", cfg)[0] == 0

    rc, out, _ = run(
        capsys,
        "benchmark",
        "compare",
        "--config",
        cfg,
        "--summary",
        "--json",
        str(tmp_path / "cmp.json"),
        "--report",
        str(tmp_path / "cmp.md"),
    )
    assert rc == 0 and "PASSED" in out
    assert json.loads((tmp_path / "cmp.json").read_text())["passed"] is True

    # Seed a security regression into the candidate: the gate must fail.
    latest = project / "results" / "latest.json"
    data = json.loads(latest.read_text())
    for case in data["cases"]:
        if case["expected"] != "allow":
            case["actual"], case["kind"] = "allow", "fn"
            break
    latest.write_text(json.dumps(data))
    rc, out, _ = run(capsys, "benchmark", "compare", "--config", cfg)
    assert rc == 1 and "security regression" in out

    rc, out, _ = run(capsys, "report", "generate", "--result", str(latest))
    assert rc == 0 and "False negatives" in out


def test_output_survives_legacy_console_encoding(monkeypatch):
    # Regression: the comparison report's check mark crashed on a cp1252 console.
    import io
    import sys

    from sqlguard_ninja.cli.main import _out

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    _out("status: ✅ PASSED")
    stream.flush()
    assert raw.getvalue() == b"status: ? PASSED\n"


def test_builtin_dataset_and_policy(capsys):
    rc, out, _ = run(capsys, "dataset", "stats", "--dataset", "builtin:v1")
    assert rc == 0 and json.loads(out)["unique_cases"] >= 500
    rc, out, _ = run(
        capsys,
        "validate",
        "--policy",
        "builtin:retail_saas",
        "--role",
        "hr_analyst",
        "--sql",
        "SELECT MAX(salary) FROM employees",
    )
    assert rc == 1 and "privacy.aggregate_only" in out
    rc, _, err = run(capsys, "validate", "--policy", "builtin:nope", "--sql", "SELECT 1")
    assert rc == 2 and "available" in err


def test_benchmark_defaults_to_builtin_without_config(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no sqlninja.yaml here
    rc, out, _ = run(capsys, "benchmark", "run", "--category", "destructive")
    assert rc == 0 and "evaluations" in out
    assert (tmp_path / "results" / "latest.json").exists()
