#!/usr/bin/env python3
"""
Evaluator for actual-budget-realrepo-001.

Usage:
    python evaluation/evaluator.py rubric.json reference/budgetmini.py doc/score_reports/score_report_reference_unit_system_v1.json

What it does:
    1. Read rubric.json.
    2. For each case, create a fresh temporary data.json.
    3. Run all commands against the target budgetmini.py.
    4. Run `state` to inspect final state.
    5. Apply checks.
    6. Write a score report JSON file.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CommandResult:
    args: List[str]
    returncode: int
    stdout: str
    stderr: str
    expected_error: bool
    passed_exit_check: bool


@dataclass
class CheckResult:
    type: str
    passed: bool
    message: str
    expected: Any = None
    actual: Any = None
    path: Optional[List[str]] = None


@dataclass
class CaseResult:
    id: str
    layer: str
    category: str
    description: str
    weight: float
    passed: bool
    earned_weight: float
    command_results: List[CommandResult]
    check_results: List[CheckResult]
    error: Optional[str] = None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_number(value: Any) -> Any:
    """
    Convert int-like and float-like strings into numbers only when safe.
    This makes checks slightly more tolerant because CLI JSON may output 60 or 60.0.
    """
    if isinstance(value, str):
        try:
            if value.strip() == "":
                return value
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value
    return value


def values_equal(actual: Any, expected: Any) -> bool:
    actual_n = normalize_number(actual)
    expected_n = normalize_number(expected)

    if isinstance(actual_n, (int, float)) and isinstance(expected_n, (int, float)):
        return abs(float(actual_n) - float(expected_n)) < 1e-9

    return actual_n == expected_n


def get_path(obj: Any, path: List[str]) -> Tuple[bool, Any]:
    """
    Get a nested value from dict/list.

    For dict:
        ["accounts", "Cash", "balance"]

    For list:
        ["items", "0", "name"]
    """
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            if key not in cur:
                return False, None
            cur = cur[key]
        elif isinstance(cur, list):
            try:
                idx = int(key)
            except ValueError:
                return False, None
            if idx < 0 or idx >= len(cur):
                return False, None
            cur = cur[idx]
        else:
            return False, None
    return True, cur


def parse_json_from_stdout(stdout: str) -> Tuple[bool, Any, str]:
    text = stdout.strip()
    if not text:
        return False, None, "stdout is empty"
    try:
        return True, json.loads(text), ""
    except json.JSONDecodeError as e:
        return False, None, f"stdout is not valid JSON: {e}"


def build_command_args(
    original_args: List[str],
    data_file_name: str,
    temp_data_file: Path,
) -> List[str]:
    """
    Rubric commands are written like:
        ["data.json", "create-account", "--name", "Cash"]

    The first arg should be replaced with the temporary data file path.
    """
    if not original_args:
        return [str(temp_data_file)]

    args = list(original_args)
    if args[0] == data_file_name or args[0].endswith(".json"):
        args[0] = str(temp_data_file)
    else:
        args.insert(0, str(temp_data_file))
    return args


def run_budget_command(
    python_executable: str,
    target_program: Path,
    args: List[str],
    timeout: int,
) -> subprocess.CompletedProcess:
    cmd = [python_executable, str(target_program)] + args
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def run_state_command(
    python_executable: str,
    target_program: Path,
    temp_data_file: Path,
    timeout: int,
) -> Tuple[bool, Any, str, CommandResult]:
    args = [str(temp_data_file), "state"]
    cp = run_budget_command(python_executable, target_program, args, timeout)
    cmd_result = CommandResult(
        args=args,
        returncode=cp.returncode,
        stdout=cp.stdout,
        stderr=cp.stderr,
        expected_error=False,
        passed_exit_check=(cp.returncode == 0),
    )

    if cp.returncode != 0:
        return False, None, f"`state` command failed: {cp.stderr.strip()}", cmd_result

    ok, state_obj, msg = parse_json_from_stdout(cp.stdout)
    if not ok:
        return False, None, f"`state` output invalid: {msg}", cmd_result

    return True, state_obj, "", cmd_result


def evaluate_check(
    check: Dict[str, Any],
    state_obj: Any,
    command_results: List[CommandResult],
) -> CheckResult:
    ctype = check.get("type")
    path = check.get("path")
    expected = check.get("expected")

    try:
        if ctype == "state_value_equals":
            exists, actual = get_path(state_obj, path)
            if not exists:
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="state path does not exist",
                    expected=expected,
                    actual=None,
                    path=path,
                )
            passed = values_equal(actual, expected)
            return CheckResult(
                type=ctype,
                passed=passed,
                message="ok" if passed else "state value mismatch",
                expected=expected,
                actual=actual,
                path=path,
            )

        if ctype == "state_path_exists":
            exists, actual = get_path(state_obj, path)
            return CheckResult(
                type=ctype,
                passed=exists,
                message="ok" if exists else "state path does not exist",
                expected="path exists",
                actual=actual if exists else None,
                path=path,
            )

        if ctype == "state_path_missing":
            exists, actual = get_path(state_obj, path)
            return CheckResult(
                type=ctype,
                passed=not exists,
                message="ok" if not exists else "state path should be missing but exists",
                expected="path missing",
                actual=actual if exists else None,
                path=path,
            )

        if ctype == "state_array_contains":
            exists, actual = get_path(state_obj, path)
            if not exists:
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="state path does not exist",
                    expected=expected,
                    actual=None,
                    path=path,
                )
            if not isinstance(actual, list):
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="state value is not an array",
                    expected=expected,
                    actual=actual,
                    path=path,
                )
            passed = expected in actual
            return CheckResult(
                type=ctype,
                passed=passed,
                message="ok" if passed else "array does not contain expected value",
                expected=expected,
                actual=actual,
                path=path,
            )

        if ctype == "stdout_json_value_equals":
            command_index = check.get("command_index")
            if command_index is None or command_index < 0 or command_index >= len(command_results):
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="invalid command_index",
                    expected=expected,
                    actual=None,
                    path=path,
                )

            stdout = command_results[command_index].stdout
            ok, stdout_obj, msg = parse_json_from_stdout(stdout)
            if not ok:
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message=msg,
                    expected=expected,
                    actual=stdout,
                    path=path,
                )

            exists, actual = get_path(stdout_obj, path)
            if not exists:
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="stdout JSON path does not exist",
                    expected=expected,
                    actual=None,
                    path=path,
                )

            passed = values_equal(actual, expected)
            return CheckResult(
                type=ctype,
                passed=passed,
                message="ok" if passed else "stdout JSON value mismatch",
                expected=expected,
                actual=actual,
                path=path,
            )

        if ctype == "stderr_contains":
            command_index = check.get("command_index")
            if command_index is None or command_index < 0 or command_index >= len(command_results):
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="invalid command_index",
                    expected=expected,
                    actual=None,
                    path=None,
                )

            stderr = command_results[command_index].stderr
            passed = str(expected).lower() in stderr.lower()
            return CheckResult(
                type=ctype,
                passed=passed,
                message="ok" if passed else "stderr does not contain expected text",
                expected=expected,
                actual=stderr,
                path=None,
            )

        if ctype == "stdout_contains":
            command_index = check.get("command_index")
            if command_index is None or command_index < 0 or command_index >= len(command_results):
                return CheckResult(
                    type=ctype,
                    passed=False,
                    message="invalid command_index",
                    expected=expected,
                    actual=None,
                    path=None,
                )

            stdout = command_results[command_index].stdout
            passed = str(expected) in stdout
            return CheckResult(
                type=ctype,
                passed=passed,
                message="ok" if passed else "stdout does not contain expected text",
                expected=expected,
                actual=stdout,
                path=None,
            )

        return CheckResult(
            type=str(ctype),
            passed=False,
            message=f"unknown check type: {ctype}",
            expected=expected,
            actual=None,
            path=path,
        )

    except Exception as e:
        return CheckResult(
            type=str(ctype),
            passed=False,
            message=f"exception while evaluating check: {e}",
            expected=expected,
            actual=None,
            path=path,
        )


def evaluate_case(
    case: Dict[str, Any],
    rubric: Dict[str, Any],
    target_program: Path,
    python_executable: str,
    timeout: int,
) -> CaseResult:
    data_file_name = rubric.get("data_file", "data.json")
    commands = case.get("commands", [])
    checks = case.get("checks", [])

    command_results: List[CommandResult] = []
    check_results: List[CheckResult] = []

    with tempfile.TemporaryDirectory(prefix=f"eval_{case.get('id', 'case')}_") as tmp:
        tmpdir = Path(tmp)
        temp_data_file = tmpdir / data_file_name

        try:
            command_exit_ok = True

            for command in commands:
                original_args = command.get("args", [])
                expected_error = bool(command.get("expect_error", False))
                args = build_command_args(original_args, data_file_name, temp_data_file)

                try:
                    cp = run_budget_command(
                        python_executable=python_executable,
                        target_program=target_program,
                        args=args,
                        timeout=timeout,
                    )
                    passed_exit_check = (cp.returncode != 0) if expected_error else (cp.returncode == 0)

                    command_results.append(
                        CommandResult(
                            args=args,
                            returncode=cp.returncode,
                            stdout=cp.stdout,
                            stderr=cp.stderr,
                            expected_error=expected_error,
                            passed_exit_check=passed_exit_check,
                        )
                    )

                    if not passed_exit_check:
                        command_exit_ok = False

                except subprocess.TimeoutExpired as e:
                    command_results.append(
                        CommandResult(
                            args=args,
                            returncode=124,
                            stdout=e.stdout or "",
                            stderr=e.stderr or f"timeout after {timeout} seconds",
                            expected_error=expected_error,
                            passed_exit_check=False,
                        )
                    )
                    command_exit_ok = False

            state_ok, state_obj, state_msg, state_cmd_result = run_state_command(
                python_executable=python_executable,
                target_program=target_program,
                temp_data_file=temp_data_file,
                timeout=timeout,
            )

            if not state_ok:
                check_results.append(
                    CheckResult(
                        type="state_command",
                        passed=False,
                        message=state_msg,
                        expected="valid state JSON",
                        actual=state_cmd_result.stdout or state_cmd_result.stderr,
                    )
                )
            else:
                for check in checks:
                    check_results.append(evaluate_check(check, state_obj, command_results))

            all_checks_ok = all(c.passed for c in check_results)
            passed = command_exit_ok and state_ok and all_checks_ok
            weight = float(case.get("weight", 0))

            return CaseResult(
                id=case.get("id", ""),
                layer=case.get("layer", ""),
                category=case.get("category", ""),
                description=case.get("description", ""),
                weight=weight,
                passed=passed,
                earned_weight=weight if passed else 0.0,
                command_results=command_results,
                check_results=check_results,
                error=None,
            )

        except Exception:
            weight = float(case.get("weight", 0))
            return CaseResult(
                id=case.get("id", ""),
                layer=case.get("layer", ""),
                category=case.get("category", ""),
                description=case.get("description", ""),
                weight=weight,
                passed=False,
                earned_weight=0.0,
                command_results=command_results,
                check_results=check_results,
                error=traceback.format_exc(),
            )


def summarize(results: List[CaseResult], rubric: Dict[str, Any]) -> Dict[str, Any]:
    total_cases = len(results)
    passed_cases = sum(1 for r in results if r.passed)

    total_weight = sum(r.weight for r in results)
    passed_weight = sum(r.earned_weight for r in results)

    unit_results = [r for r in results if r.layer == "unit"]
    system_results = [r for r in results if r.layer == "system"]

    unit_weight = sum(r.weight for r in unit_results)
    unit_passed_weight = sum(r.earned_weight for r in unit_results)

    system_weight = sum(r.weight for r in system_results)
    system_passed_weight = sum(r.earned_weight for r in system_results)

    score = passed_weight / total_weight if total_weight else 0.0
    unit_score = unit_passed_weight / unit_weight if unit_weight else 0.0
    system_score = system_passed_weight / system_weight if system_weight else 0.0

    # This follows the project idea: how much better unit tests look than system tests.
    unit_system_gap = unit_score - system_score

    return {
        "task_id": rubric.get("task_id"),
        "task_name": rubric.get("task_name"),
        "version": rubric.get("version"),
        "entrypoint": rubric.get("entrypoint"),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "total_weight": total_weight,
        "passed_weight": passed_weight,
        "score": round(score, 6),
        "unit_score": {
            "cases": len(unit_results),
            "passed_cases": sum(1 for r in unit_results if r.passed),
            "total_weight": unit_weight,
            "passed_weight": unit_passed_weight,
            "score": round(unit_score, 6),
        },
        "system_score": {
            "cases": len(system_results),
            "passed_cases": sum(1 for r in system_results if r.passed),
            "total_weight": system_weight,
            "passed_weight": system_passed_weight,
            "score": round(system_score, 6),
        },
        "unit_system_gap": round(unit_system_gap, 6),
        "case_results": [asdict(r) for r in results],
    }


def print_summary(report: Dict[str, Any]) -> None:
    print(f"Task: {report.get('task_id')}")
    print(f"Total cases: {report['total_cases']}")
    print(f"Passed cases: {report['passed_cases']}")
    print(f"Failed cases: {report['failed_cases']}")
    print(f"Score: {report['score']}")
    print(f"Unit score: {report['unit_score']['score']}")
    print(f"System score: {report['system_score']['score']}")
    print(f"Unit-system gap: {report['unit_system_gap']}")

    if report["failed_cases"] > 0:
        print("\nFailed cases:")
        for case in report["case_results"]:
            if not case["passed"]:
                print(f"  - {case['id']}: {case['description']}")
                if case.get("error"):
                    print("    internal error")
                for cmd in case.get("command_results", []):
                    if not cmd.get("passed_exit_check", True):
                        print(
                            f"    command failed exit check: args={cmd.get('args')} "
                            f"returncode={cmd.get('returncode')} "
                            f"stderr={cmd.get('stderr', '').strip()}"
                        )
                for chk in case.get("check_results", []):
                    if not chk.get("passed", True):
                        print(
                            f"    check failed: {chk.get('type')} "
                            f"path={chk.get('path')} "
                            f"expected={chk.get('expected')} "
                            f"actual={chk.get('actual')} "
                            f"message={chk.get('message')}"
                        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rubric against a budgetmini.py implementation.")
    parser.add_argument("rubric_path", help="Path to rubric.json")
    parser.add_argument("target_program", help="Path to budgetmini.py to evaluate")
    parser.add_argument("output_path", help="Path to write score report JSON")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout seconds for each command")
    args = parser.parse_args()

    rubric_path = Path(args.rubric_path).resolve()
    target_program = Path(args.target_program).resolve()
    output_path = Path(args.output_path).resolve()

    if not rubric_path.exists():
        print(f"error: rubric file not found: {rubric_path}", file=sys.stderr)
        return 2

    if not target_program.exists():
        print(f"error: target program not found: {target_program}", file=sys.stderr)
        return 2

    try:
        rubric = load_json(rubric_path)
    except json.JSONDecodeError as e:
        print(f"error: rubric is not valid JSON: {e}", file=sys.stderr)
        return 2

    cases = rubric.get("cases", [])
    if not isinstance(cases, list):
        print("error: rubric field `cases` must be a list", file=sys.stderr)
        return 2

    results: List[CaseResult] = []
    for case in cases:
        result = evaluate_case(
            case=case,
            rubric=rubric,
            target_program=target_program,
            python_executable=args.python,
            timeout=args.timeout,
        )
        results.append(result)

    report = summarize(results, rubric)
    write_json(output_path, report)
    print_summary(report)

    return 0 if report["failed_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
