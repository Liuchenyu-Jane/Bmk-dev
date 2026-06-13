#!/usr/bin/env python3
"""
Reference implementation for Actual Budget Mini Finance Task.

Usage:
    python budgetmini.py <data_file> <command> [options]

This is intentionally small and explicit. It stores all financial state in a JSON
file and recalculates balances, budgets, and reports from transactions whenever
state is saved or queried.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from typing import Any, Dict, List, Optional


State = Dict[str, Any]


def empty_state() -> State:
    return {
        "accounts": {},
        "transactions": {},
        "category_groups": {},
        "categories": {},
        "budgets": {},
        "rules": {},
        "schedules": {},
        "reports": {},
        "payees": {},
        "tags": {},
    }


def load_state(path: str) -> State:
    if not os.path.exists(path):
        return empty_state()
    with open(path, "r", encoding="utf-8") as f:
        if os.path.getsize(path) == 0:
            return empty_state()
        data = json.load(f)
    state = empty_state()
    if isinstance(data, dict):
        state.update(data)
    for key, default in empty_state().items():
        if key not in state or not isinstance(state[key], type(default)):
            state[key] = default
    return state


def save_state(path: str, state: State) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def parse_amount(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        amount = float(value)
    except ValueError:
        fail(f"invalid amount: {value}")
    if amount < 0:
        fail("amount cannot be negative")
    # Use int when possible so JSON checks can compare cleanly to integers.
    return int(amount) if amount.is_integer() else amount


def month_of(date: str) -> str:
    if not date or len(date) < 7:
        fail("date must be in YYYY-MM-DD format")
    return date[:7]


def ensure_payee(state: State, name: Optional[str]) -> None:
    if name:
        state["payees"].setdefault(name, {"name": name})


def ensure_tag(state: State, name: str) -> None:
    state["tags"].setdefault(name, {"name": name})


def ensure_category_exists_or_create_loose(state: State, category: Optional[str]) -> None:
    """Create a loose category record if a command supplies a category that was not
    explicitly created. This keeps the mini implementation forgiving for simple
    transaction tests, while explicit budget/category commands still validate.
    """
    if category and category not in state["categories"]:
        state["categories"][category] = {"name": category, "group": None}


def recompute(state: State) -> None:
    # Reset account balances.
    for account in state["accounts"].values():
        account["balance"] = 0

    # Reset budget computed fields while preserving budgeted values.
    for month, cats in state["budgets"].items():
        for category, row in cats.items():
            row.setdefault("budgeted", 0)
            row["spent"] = 0
            row["balance"] = row.get("budgeted", 0)

    reports: Dict[str, Dict[str, Any]] = {}

    for tx in state["transactions"].values():
        account_name = tx.get("account")
        payment = tx.get("payment", 0) or 0
        deposit = tx.get("deposit", 0) or 0
        tx_month = month_of(tx.get("date", "0000-00-00"))

        if account_name in state["accounts"]:
            state["accounts"][account_name]["balance"] += deposit - payment

        report = reports.setdefault(
            tx_month,
            {
                "month": tx_month,
                "total_income": 0,
                "total_expenses": 0,
                "average_per_month": 0,
                "average_per_transaction": 0,
                "net_worth": 0,
                "cash_flow": 0,
                "transaction_count": 0,
                "budget_overview": {},
            },
        )
        report["total_income"] += deposit
        report["total_expenses"] += payment
        report["transaction_count"] += 1

        category = tx.get("category")
        if category and payment > 0:
            state["budgets"].setdefault(tx_month, {})
            state["budgets"][tx_month].setdefault(
                category, {"budgeted": 0, "spent": 0, "balance": 0}
            )
            state["budgets"][tx_month][category]["spent"] += payment

    for month, cats in state["budgets"].items():
        for category, row in cats.items():
            row["balance"] = row.get("budgeted", 0) - row.get("spent", 0)

    net_worth = sum((acc.get("balance", 0) or 0) for acc in state["accounts"].values())
    for month, report in reports.items():
        report["cash_flow"] = report["total_income"] - report["total_expenses"]
        count = report["transaction_count"]
        total_abs = report["total_income"] + report["total_expenses"]
        report["average_per_transaction"] = total_abs / count if count else 0
        report["average_per_month"] = report["cash_flow"]
        report["net_worth"] = net_worth
        report["budget_overview"] = copy.deepcopy(state["budgets"].get(month, {}))

    # Also expose report rows for months that only have budgets.
    for month in state["budgets"]:
        reports.setdefault(
            month,
            {
                "month": month,
                "total_income": 0,
                "total_expenses": 0,
                "average_per_month": 0,
                "average_per_transaction": 0,
                "net_worth": net_worth,
                "cash_flow": 0,
                "transaction_count": 0,
                "budget_overview": copy.deepcopy(state["budgets"].get(month, {})),
            },
        )

    state["reports"] = reports


def get_report(state: State, month: str) -> Dict[str, Any]:
    recompute(state)
    if month not in state["reports"]:
        net_worth = sum((acc.get("balance", 0) or 0) for acc in state["accounts"].values())
        return {
            "month": month,
            "total_income": 0,
            "total_expenses": 0,
            "average_per_month": 0,
            "average_per_transaction": 0,
            "net_worth": net_worth,
            "cash_flow": 0,
            "transaction_count": 0,
            "budget_overview": copy.deepcopy(state["budgets"].get(month, {})),
        }
    return state["reports"][month]


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def cmd_create_account(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        fail("account name is required")
    if args.name in state["accounts"]:
        fail("account already exists")
    state["accounts"][args.name] = {
        "id": args.name,
        "name": args.name,
        "type": args.type or "checking",
        "on_budget": bool(args.on_budget),
        "balance": 0,
    }


def cmd_rename_account(state: State, args: argparse.Namespace) -> None:
    if args.old not in state["accounts"]:
        fail("account not found")
    if args.new in state["accounts"]:
        fail("new account name already exists")
    account = state["accounts"].pop(args.old)
    account["name"] = args.new
    account["id"] = args.new
    state["accounts"][args.new] = account
    for tx in state["transactions"].values():
        if tx.get("account") == args.old:
            tx["account"] = args.new
    for schedule in state["schedules"].values():
        if schedule.get("account") == args.old:
            schedule["account"] = args.new


def cmd_list_accounts(state: State, args: argparse.Namespace) -> None:
    recompute(state)
    print_json(list(state["accounts"].values()))


def cmd_create_category_group(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        fail("category group name is required")
    if args.name in state["category_groups"]:
        fail("category group already exists")
    state["category_groups"][args.name] = {"name": args.name, "categories": []}


def cmd_rename_category_group(state: State, args: argparse.Namespace) -> None:
    if args.old not in state["category_groups"]:
        fail("category group not found")
    if args.new in state["category_groups"]:
        fail("new category group already exists")
    group = state["category_groups"].pop(args.old)
    group["name"] = args.new
    state["category_groups"][args.new] = group
    for cat in state["categories"].values():
        if cat.get("group") == args.old:
            cat["group"] = args.new


def cmd_create_category(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        fail("category name is required")
    if args.group not in state["category_groups"]:
        fail("category group not found")
    if args.name in state["categories"]:
        fail("category already exists")
    state["categories"][args.name] = {"name": args.name, "group": args.group}
    cats = state["category_groups"][args.group].setdefault("categories", [])
    if args.name not in cats:
        cats.append(args.name)


def cmd_rename_category(state: State, args: argparse.Namespace) -> None:
    if args.old not in state["categories"]:
        fail("category not found")
    if args.new in state["categories"]:
        fail("new category name already exists")
    category = state["categories"].pop(args.old)
    group = category.get("group")
    category["name"] = args.new
    state["categories"][args.new] = category

    if group and group in state["category_groups"]:
        cats = state["category_groups"][group].setdefault("categories", [])
        state["category_groups"][group]["categories"] = [args.new if c == args.old else c for c in cats]

    for tx in state["transactions"].values():
        if tx.get("category") == args.old:
            tx["category"] = args.new

    for month, cats in list(state["budgets"].items()):
        if args.old in cats:
            old_row = cats.pop(args.old)
            if args.new in cats:
                cats[args.new]["budgeted"] = cats[args.new].get("budgeted", 0) + old_row.get("budgeted", 0)
            else:
                cats[args.new] = old_row

    for rule in state["rules"].values():
        if rule.get("set_category") == args.old:
            rule["set_category"] = args.new
    for schedule in state["schedules"].values():
        if schedule.get("category") == args.old:
            schedule["category"] = args.new


def cmd_set_budget(state: State, args: argparse.Namespace) -> None:
    if args.category not in state["categories"]:
        fail("category not found")
    amount = parse_amount(args.amount)
    state["budgets"].setdefault(args.month, {})
    state["budgets"][args.month].setdefault(args.category, {"budgeted": 0, "spent": 0, "balance": 0})
    state["budgets"][args.month][args.category]["budgeted"] = amount


def cmd_show_budget(state: State, args: argparse.Namespace) -> None:
    recompute(state)
    print_json(state["budgets"].get(args.month, {}))


def validate_transaction_fields(state: State, tx: Dict[str, Any], require_account: bool = True) -> None:
    if require_account and not tx.get("account"):
        fail("account is required")
    if tx.get("account") and tx["account"] not in state["accounts"]:
        fail("account not found")
    payment = tx.get("payment", 0) or 0
    deposit = tx.get("deposit", 0) or 0
    if payment > 0 and deposit > 0:
        fail("transaction cannot have both payment and deposit")
    if payment == 0 and deposit == 0:
        fail("transaction amount is required")


def cmd_add_transaction(state: State, args: argparse.Namespace) -> None:
    if not args.id:
        fail("transaction id is required")
    if args.id in state["transactions"]:
        fail("transaction already exists")
    payment = parse_amount(args.payment, 0)
    deposit = parse_amount(args.deposit, 0)
    tx = {
        "id": args.id,
        "date": args.date,
        "account": args.account,
        "payee": args.payee,
        "notes": args.notes or "",
        "category": args.category,
        "payment": payment,
        "deposit": deposit,
        "tags": [],
    }
    validate_transaction_fields(state, tx)
    ensure_category_exists_or_create_loose(state, args.category)
    ensure_payee(state, args.payee)
    state["transactions"][args.id] = tx


def cmd_edit_transaction(state: State, args: argparse.Namespace) -> None:
    if args.id not in state["transactions"]:
        fail("transaction not found")
    tx = copy.deepcopy(state["transactions"][args.id])
    for field in ["date", "account", "payee", "notes", "category"]:
        value = getattr(args, field)
        if value is not None:
            tx[field] = value
    if args.payment is not None:
        tx["payment"] = parse_amount(args.payment)
    if args.deposit is not None:
        tx["deposit"] = parse_amount(args.deposit)
    validate_transaction_fields(state, tx)
    ensure_category_exists_or_create_loose(state, tx.get("category"))
    ensure_payee(state, tx.get("payee"))
    state["transactions"][args.id] = tx


def cmd_delete_transaction(state: State, args: argparse.Namespace) -> None:
    if args.id not in state["transactions"]:
        fail("transaction not found")
    del state["transactions"][args.id]


def cmd_assign_category(state: State, args: argparse.Namespace) -> None:
    if args.transaction not in state["transactions"]:
        fail("transaction not found")
    if args.category not in state["categories"]:
        fail("category not found")
    state["transactions"][args.transaction]["category"] = args.category


def cmd_list_transactions(state: State, args: argparse.Namespace) -> None:
    recompute(state)
    rows = list(state["transactions"].values())
    if args.account:
        rows = [tx for tx in rows if tx.get("account") == args.account]
    if args.category:
        rows = [tx for tx in rows if tx.get("category") == args.category]
    if args.payee:
        rows = [tx for tx in rows if tx.get("payee") == args.payee]
    if args.month:
        rows = [tx for tx in rows if month_of(tx.get("date", "")) == args.month]
    rows.sort(key=lambda tx: (tx.get("date", ""), tx.get("id", "")))
    print_json(rows)


def cmd_report(state: State, args: argparse.Namespace) -> None:
    print_json(get_report(state, args.month))


def cmd_state(state: State, args: argparse.Namespace) -> None:
    recompute(state)
    print_json(state)


def cmd_create_rule(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        fail("rule name is required")
    if args.field != "payee":
        fail("only payee rules are supported")
    if not args.equals:
        fail("rule equals value is required")
    if not args.set_category:
        fail("set-category is required")
    ensure_category_exists_or_create_loose(state, args.set_category)
    state["rules"][args.name] = {
        "name": args.name,
        "field": args.field,
        "equals": args.equals,
        "set_category": args.set_category,
    }


def cmd_apply_rules(state: State, args: argparse.Namespace) -> None:
    for tx in state["transactions"].values():
        for rule in state["rules"].values():
            field = rule.get("field")
            if field == "payee" and tx.get("payee") == rule.get("equals"):
                tx["category"] = rule.get("set_category")


def cmd_create_schedule(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        fail("schedule name is required")
    if args.name in state["schedules"]:
        fail("schedule already exists")
    if args.account not in state["accounts"]:
        fail("account not found")
    if args.direction not in ("payment", "deposit"):
        fail("direction must be payment or deposit")
    amount = parse_amount(args.amount)
    if amount <= 0:
        fail("schedule amount must be greater than 0")
    ensure_category_exists_or_create_loose(state, args.category)
    ensure_payee(state, args.payee)
    state["schedules"][args.name] = {
        "id": args.name,
        "name": args.name,
        "payee": args.payee,
        "account": args.account,
        "category": args.category,
        "amount": amount,
        "direction": args.direction,
        "repeat": args.repeat,
        "day": int(args.day),
        "can_generate_transaction": True,
    }


def cmd_generate_scheduled_transaction(state: State, args: argparse.Namespace) -> None:
    if args.schedule not in state["schedules"]:
        fail("schedule not found")
    if args.id in state["transactions"]:
        fail("transaction already exists")
    schedule = state["schedules"][args.schedule]
    amount = schedule.get("amount", 0)
    payment = amount if schedule.get("direction") == "payment" else 0
    deposit = amount if schedule.get("direction") == "deposit" else 0
    tx = {
        "id": args.id,
        "date": args.date,
        "account": schedule.get("account"),
        "payee": schedule.get("payee"),
        "notes": f"generated from schedule: {args.schedule}",
        "category": schedule.get("category"),
        "payment": payment,
        "deposit": deposit,
        "tags": [],
        "schedule": args.schedule,
    }
    validate_transaction_fields(state, tx)
    state["transactions"][args.id] = tx


def cmd_assign_tag(state: State, args: argparse.Namespace) -> None:
    if args.transaction not in state["transactions"]:
        fail("transaction not found")
    ensure_tag(state, args.tag)
    tags = state["transactions"][args.transaction].setdefault("tags", [])
    if args.tag not in tags:
        tags.append(args.tag)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budgetmini.py")
    parser.add_argument("data_file")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-account")
    p.add_argument("--name", required=True)
    p.add_argument("--type", default="checking")
    p.add_argument("--on-budget", action="store_true")
    p.set_defaults(func=cmd_create_account, outputs_json=False)

    p = sub.add_parser("rename-account")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(func=cmd_rename_account, outputs_json=False)

    p = sub.add_parser("list-accounts")
    p.set_defaults(func=cmd_list_accounts, outputs_json=True)

    p = sub.add_parser("create-category-group")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_category_group, outputs_json=False)

    p = sub.add_parser("rename-category-group")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(func=cmd_rename_category_group, outputs_json=False)

    p = sub.add_parser("create-category")
    p.add_argument("--group", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_category, outputs_json=False)

    p = sub.add_parser("rename-category")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(func=cmd_rename_category, outputs_json=False)

    p = sub.add_parser("set-budget")
    p.add_argument("--month", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--amount", required=True)
    p.set_defaults(func=cmd_set_budget, outputs_json=False)

    p = sub.add_parser("show-budget")
    p.add_argument("--month", required=True)
    p.set_defaults(func=cmd_show_budget, outputs_json=True)

    p = sub.add_parser("add-transaction")
    p.add_argument("--id", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--account")
    p.add_argument("--payee")
    p.add_argument("--notes")
    p.add_argument("--category")
    p.add_argument("--payment")
    p.add_argument("--deposit")
    p.set_defaults(func=cmd_add_transaction, outputs_json=False)

    p = sub.add_parser("edit-transaction")
    p.add_argument("--id", required=True)
    p.add_argument("--date")
    p.add_argument("--account")
    p.add_argument("--payee")
    p.add_argument("--notes")
    p.add_argument("--category")
    p.add_argument("--payment")
    p.add_argument("--deposit")
    p.set_defaults(func=cmd_edit_transaction, outputs_json=False)

    p = sub.add_parser("delete-transaction")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_delete_transaction, outputs_json=False)

    p = sub.add_parser("assign-category")
    p.add_argument("--transaction", required=True)
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_assign_category, outputs_json=False)

    p = sub.add_parser("list-transactions")
    p.add_argument("--account")
    p.add_argument("--category")
    p.add_argument("--payee")
    p.add_argument("--month")
    p.set_defaults(func=cmd_list_transactions, outputs_json=True)

    p = sub.add_parser("report")
    p.add_argument("--month", required=True)
    p.set_defaults(func=cmd_report, outputs_json=True)

    p = sub.add_parser("state")
    p.set_defaults(func=cmd_state, outputs_json=True)

    p = sub.add_parser("create-rule")
    p.add_argument("--name", required=True)
    p.add_argument("--field", required=True)
    p.add_argument("--equals", required=True)
    p.add_argument("--set-category", dest="set_category", required=True)
    p.set_defaults(func=cmd_create_rule, outputs_json=False)

    p = sub.add_parser("apply-rules")
    p.set_defaults(func=cmd_apply_rules, outputs_json=False)

    p = sub.add_parser("create-schedule")
    p.add_argument("--name", required=True)
    p.add_argument("--payee", required=True)
    p.add_argument("--account", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--direction", required=True)
    p.add_argument("--repeat", default="monthly")
    p.add_argument("--day", required=True)
    p.set_defaults(func=cmd_create_schedule, outputs_json=False)

    p = sub.add_parser("generate-scheduled-transaction")
    p.add_argument("--schedule", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_generate_scheduled_transaction, outputs_json=False)

    p = sub.add_parser("assign-tag")
    p.add_argument("--transaction", required=True)
    p.add_argument("--tag", required=True)
    p.set_defaults(func=cmd_assign_tag, outputs_json=False)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    original_state = load_state(args.data_file)
    state = copy.deepcopy(original_state)

    try:
        args.func(state, args)
        recompute(state)
        save_state(args.data_file, state)
        if not getattr(args, "outputs_json", False):
            print("ok")
        return 0
    except SystemExit as e:
        # State is not saved when a command fails.
        if isinstance(e.code, int):
            return e.code
        return 2
    except Exception as exc:  # Keep errors explicit and atomic.
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
