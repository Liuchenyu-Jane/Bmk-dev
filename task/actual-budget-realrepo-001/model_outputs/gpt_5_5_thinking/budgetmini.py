#!/usr/bin/env python3
"""
budgetmini.py - A simplified local-first personal finance CLI.

Usage:
    python budgetmini.py <data_file> <command> [options]

The program stores state in JSON and recalculates derived account balances,
budget spent/balance values, and reports from transactions each time they are
shown or saved.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple


State = Dict[str, Any]
MONEY_Q = Decimal("0.01")


class BudgetMiniError(Exception):
    """Expected user-facing command error."""


def money(value: Any, field_name: str = "amount") -> Decimal:
    """Parse and validate a non-negative money amount."""
    if value is None:
        return Decimal("0")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BudgetMiniError(f"{field_name} must be a valid number")
    if d < 0:
        raise BudgetMiniError(f"{field_name} must be non-negative")
    return d.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def money_out(value: Decimal | int | float | str) -> int | float:
    """Return a stable JSON number: int when possible, otherwise float with 2 dp."""
    d = Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def month_of(date_str: str) -> str:
    if not isinstance(date_str, str) or len(date_str) < 7:
        raise BudgetMiniError("date must be in YYYY-MM-DD format")
    month = date_str[:7]
    if len(month) != 7 or month[4] != "-" or not month[:4].isdigit() or not month[5:7].isdigit():
        raise BudgetMiniError("date must be in YYYY-MM-DD format")
    return month


def validate_month(month: str) -> str:
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-" or not month[:4].isdigit() or not month[5:7].isdigit():
        raise BudgetMiniError("month must be in YYYY-MM format")
    mm = int(month[5:7])
    if mm < 1 or mm > 12:
        raise BudgetMiniError("month must be in YYYY-MM format")
    return month


def empty_state() -> State:
    return {
        "accounts": {},
        "transactions": {},
        "category_groups": {},
        "categories": {},
        "budgets": {},
        "rules": {},
        "schedules": {},
        "payees": {},
        "tags": {},
    }


def normalize_state(raw: Any) -> State:
    if not isinstance(raw, dict):
        raise BudgetMiniError("data file must contain a JSON object")
    state = empty_state()
    for key in state:
        val = raw.get(key, {})
        if not isinstance(val, dict):
            raise BudgetMiniError(f"state field {key} must be an object")
        state[key] = val
    return state


def load_state(path: str) -> State:
    if not os.path.exists(path):
        return empty_state()
    if os.path.getsize(path) == 0:
        return empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalize_state(json.load(f))
    except json.JSONDecodeError as e:
        raise BudgetMiniError(f"invalid JSON data file: {e}")


def save_state(path: str, state: State) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".budgetmini-", suffix=".json", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(public_state(state), f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def account_exists(state: State, name: Optional[str]) -> bool:
    return bool(name) and name in state["accounts"]


def category_exists(state: State, name: Optional[str]) -> bool:
    return bool(name) and name in state["categories"]


def ensure_account(state: State, name: Optional[str]) -> str:
    if not name:
        raise BudgetMiniError("account is required")
    if name not in state["accounts"]:
        raise BudgetMiniError(f"account not found: {name}")
    return name


def ensure_category(state: State, name: Optional[str], *, required: bool = True) -> Optional[str]:
    if not name:
        if required:
            raise BudgetMiniError("category is required")
        return None
    if name not in state["categories"]:
        raise BudgetMiniError(f"category not found: {name}")
    return name


def ensure_transaction(state: State, txid: str) -> Dict[str, Any]:
    if not txid:
        raise BudgetMiniError("transaction id is required")
    if txid not in state["transactions"]:
        raise BudgetMiniError(f"transaction not found: {txid}")
    return state["transactions"][txid]


def add_payee_if_needed(state: State, payee: Optional[str]) -> None:
    if payee:
        state["payees"].setdefault(payee, {"name": payee})


def add_tag_if_needed(state: State, tag: str) -> None:
    if tag:
        state["tags"].setdefault(tag, {"name": tag})


def validate_transaction_amounts(payment: Any, deposit: Any) -> Tuple[Decimal, Decimal]:
    p = money(payment, "payment")
    d = money(deposit, "deposit")
    if p > 0 and d > 0:
        raise BudgetMiniError("transaction cannot have both payment and deposit")
    if p == 0 and d == 0:
        raise BudgetMiniError("transaction must have a payment or deposit amount")
    return p, d


def apply_rules_to_transaction(state: State, tx: Dict[str, Any]) -> bool:
    changed = False
    for rule in state["rules"].values():
        cond = rule.get("condition", {})
        action = rule.get("action", {})
        field = cond.get("field")
        equals = cond.get("equals")
        if field and str(tx.get(field, "")) == str(equals):
            if "set_category" in action:
                cat = action["set_category"]
                ensure_category(state, cat)
                if tx.get("category") != cat:
                    tx["category"] = cat
                    changed = True
    return changed


def account_balances(state: State) -> Dict[str, Decimal]:
    balances = {name: Decimal("0") for name in state["accounts"]}
    for tx in state["transactions"].values():
        acct = tx.get("account")
        if acct in balances:
            balances[acct] += Decimal(str(tx.get("deposit", 0))) - Decimal(str(tx.get("payment", 0)))
    return {k: v.quantize(MONEY_Q, rounding=ROUND_HALF_UP) for k, v in balances.items()}


def category_spent(state: State, month: str) -> Dict[str, Decimal]:
    spent = {name: Decimal("0") for name in state["categories"]}
    for tx in state["transactions"].values():
        if month_of(tx.get("date", "")) != month:
            continue
        cat = tx.get("category")
        if cat in spent:
            spent[cat] += Decimal(str(tx.get("payment", 0)))
    return {k: v.quantize(MONEY_Q, rounding=ROUND_HALF_UP) for k, v in spent.items()}


def budget_for_month(state: State, month: str) -> Dict[str, Dict[str, int | float]]:
    validate_month(month)
    raw_budget = state["budgets"].get(month, {})
    spent = category_spent(state, month)
    categories = sorted(set(state["categories"].keys()) | set(raw_budget.keys()))
    output: Dict[str, Dict[str, int | float]] = {}
    for cat in categories:
        budgeted = money(raw_budget.get(cat, {}).get("budgeted", 0), "budgeted")
        s = spent.get(cat, Decimal("0"))
        output[cat] = {
            "budgeted": money_out(budgeted),
            "spent": money_out(s),
            "balance": money_out(budgeted - s),
        }
    return output


def months_in_state(state: State) -> List[str]:
    months = set(state["budgets"].keys())
    for tx in state["transactions"].values():
        try:
            months.add(month_of(tx.get("date", "")))
        except BudgetMiniError:
            pass
    return sorted(months)


def report_for_month(state: State, month: str) -> Dict[str, Any]:
    validate_month(month)
    total_income = Decimal("0")
    total_expenses = Decimal("0")
    tx_count = 0
    for tx in state["transactions"].values():
        if month_of(tx.get("date", "")) == month:
            total_income += Decimal(str(tx.get("deposit", 0)))
            total_expenses += Decimal(str(tx.get("payment", 0)))
            tx_count += 1
    cash_flow = total_income - total_expenses
    net_worth = sum(account_balances(state).values(), Decimal("0"))
    avg_per_tx = (total_income + total_expenses) / tx_count if tx_count else Decimal("0")
    months = months_in_state(state)
    month_count = max(len(months), 1)
    total_abs_all_months = Decimal("0")
    for tx in state["transactions"].values():
        total_abs_all_months += Decimal(str(tx.get("deposit", 0))) + Decimal(str(tx.get("payment", 0)))
    return {
        "month": month,
        "total_income": money_out(total_income),
        "total_expenses": money_out(total_expenses),
        "average_per_month": money_out(total_abs_all_months / month_count),
        "average_per_transaction": money_out(avg_per_tx),
        "net_worth": money_out(net_worth),
        "cash_flow": money_out(cash_flow),
        "budget_overview": budget_for_month(state, month),
    }


def public_accounts(state: State) -> Dict[str, Dict[str, Any]]:
    balances = account_balances(state)
    result = copy.deepcopy(state["accounts"])
    for name, account in result.items():
        account["balance"] = money_out(balances.get(name, Decimal("0")))
    return result


def public_budgets(state: State) -> Dict[str, Dict[str, Dict[str, int | float]]]:
    return {month: budget_for_month(state, month) for month in months_in_state(state)}


def public_reports(state: State) -> Dict[str, Dict[str, Any]]:
    return {month: report_for_month(state, month) for month in months_in_state(state)}


def public_state(state: State) -> State:
    out = copy.deepcopy(state)
    out["accounts"] = public_accounts(state)
    out["budgets"] = public_budgets(state)
    out["reports"] = public_reports(state)
    return out


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))


# Command handlers

def cmd_create_account(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        raise BudgetMiniError("account name is required")
    if args.name in state["accounts"]:
        raise BudgetMiniError(f"account already exists: {args.name}")
    state["accounts"][args.name] = {
        "name": args.name,
        "type": args.type,
        "on_budget": bool(args.on_budget),
    }
    print("ok")


def cmd_rename_account(state: State, args: argparse.Namespace) -> None:
    ensure_account(state, args.old)
    if not args.new:
        raise BudgetMiniError("new account name is required")
    if args.new in state["accounts"]:
        raise BudgetMiniError(f"account already exists: {args.new}")
    account = state["accounts"].pop(args.old)
    account["name"] = args.new
    state["accounts"][args.new] = account
    for tx in state["transactions"].values():
        if tx.get("account") == args.old:
            tx["account"] = args.new
    for sched in state["schedules"].values():
        if sched.get("account") == args.old:
            sched["account"] = args.new
    print("ok")


def cmd_list_accounts(state: State, args: argparse.Namespace) -> None:
    print_json(public_accounts(state))


def cmd_create_category_group(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        raise BudgetMiniError("category group name is required")
    if args.name in state["category_groups"]:
        raise BudgetMiniError(f"category group already exists: {args.name}")
    state["category_groups"][args.name] = {"name": args.name, "categories": []}
    print("ok")


def cmd_rename_category_group(state: State, args: argparse.Namespace) -> None:
    if args.old not in state["category_groups"]:
        raise BudgetMiniError(f"category group not found: {args.old}")
    if args.new in state["category_groups"]:
        raise BudgetMiniError(f"category group already exists: {args.new}")
    group = state["category_groups"].pop(args.old)
    group["name"] = args.new
    state["category_groups"][args.new] = group
    for cat in state["categories"].values():
        if cat.get("group") == args.old:
            cat["group"] = args.new
    print("ok")


def cmd_create_category(state: State, args: argparse.Namespace) -> None:
    if args.group not in state["category_groups"]:
        raise BudgetMiniError(f"category group not found: {args.group}")
    if args.name in state["categories"]:
        raise BudgetMiniError(f"category already exists: {args.name}")
    state["categories"][args.name] = {"name": args.name, "group": args.group}
    cats = state["category_groups"][args.group].setdefault("categories", [])
    if args.name not in cats:
        cats.append(args.name)
    print("ok")


def cmd_rename_category(state: State, args: argparse.Namespace) -> None:
    ensure_category(state, args.old)
    if args.new in state["categories"]:
        raise BudgetMiniError(f"category already exists: {args.new}")
    cat = state["categories"].pop(args.old)
    group = cat.get("group")
    cat["name"] = args.new
    state["categories"][args.new] = cat
    if group in state["category_groups"]:
        state["category_groups"][group]["categories"] = [args.new if c == args.old else c for c in state["category_groups"][group].get("categories", [])]
    for tx in state["transactions"].values():
        if tx.get("category") == args.old:
            tx["category"] = args.new
    for month, mb in state["budgets"].items():
        if args.old in mb:
            mb[args.new] = mb.pop(args.old)
    for rule in state["rules"].values():
        if rule.get("action", {}).get("set_category") == args.old:
            rule["action"]["set_category"] = args.new
    for sched in state["schedules"].values():
        if sched.get("category") == args.old:
            sched["category"] = args.new
    print("ok")


def cmd_set_budget(state: State, args: argparse.Namespace) -> None:
    validate_month(args.month)
    ensure_category(state, args.category)
    amt = money(args.amount, "amount")
    state["budgets"].setdefault(args.month, {})[args.category] = {"budgeted": money_out(amt)}
    print("ok")


def cmd_show_budget(state: State, args: argparse.Namespace) -> None:
    print_json(budget_for_month(state, validate_month(args.month)))


def build_transaction(state: State, *, txid: str, date: str, account: str, payee: Optional[str], notes: Optional[str], category: Optional[str], payment: Any, deposit: Any, tags: Optional[List[str]], schedule: Optional[str] = None) -> Dict[str, Any]:
    if not txid:
        raise BudgetMiniError("transaction id is required")
    month_of(date)
    ensure_account(state, account)
    if category:
        ensure_category(state, category)
    p, d = validate_transaction_amounts(payment, deposit)
    clean_tags = []
    for tag in tags or []:
        if tag and tag not in clean_tags:
            clean_tags.append(tag)
    tx = {
        "id": txid,
        "date": date,
        "account": account,
        "payee": payee or "",
        "notes": notes or "",
        "category": category or "",
        "payment": money_out(p),
        "deposit": money_out(d),
        "tags": clean_tags,
    }
    if schedule:
        tx["schedule"] = schedule
    return tx


def cmd_add_transaction(state: State, args: argparse.Namespace) -> None:
    if args.id in state["transactions"]:
        raise BudgetMiniError(f"transaction already exists: {args.id}")
    tx = build_transaction(
        state,
        txid=args.id,
        date=args.date,
        account=args.account,
        payee=args.payee,
        notes=args.notes,
        category=args.category,
        payment=args.payment,
        deposit=args.deposit,
        tags=args.tags,
    )
    apply_rules_to_transaction(state, tx)
    state["transactions"][args.id] = tx
    add_payee_if_needed(state, tx.get("payee"))
    for tag in tx.get("tags", []):
        add_tag_if_needed(state, tag)
    print("ok")


def cmd_edit_transaction(state: State, args: argparse.Namespace) -> None:
    tx = copy.deepcopy(ensure_transaction(state, args.id))
    if args.date is not None:
        month_of(args.date)
        tx["date"] = args.date
    if args.account is not None:
        ensure_account(state, args.account)
        tx["account"] = args.account
    if args.payee is not None:
        tx["payee"] = args.payee
    if args.notes is not None:
        tx["notes"] = args.notes
    if args.category is not None:
        if args.category:
            ensure_category(state, args.category)
        tx["category"] = args.category
    payment = tx.get("payment", 0) if args.payment is None else args.payment
    deposit = tx.get("deposit", 0) if args.deposit is None else args.deposit
    p, d = validate_transaction_amounts(payment, deposit)
    tx["payment"] = money_out(p)
    tx["deposit"] = money_out(d)
    if args.tags is not None:
        tx["tags"] = list(dict.fromkeys([t for t in args.tags if t]))
    apply_rules_to_transaction(state, tx)
    state["transactions"][args.id] = tx
    add_payee_if_needed(state, tx.get("payee"))
    for tag in tx.get("tags", []):
        add_tag_if_needed(state, tag)
    print("ok")


def cmd_delete_transaction(state: State, args: argparse.Namespace) -> None:
    ensure_transaction(state, args.id)
    del state["transactions"][args.id]
    print("ok")


def cmd_assign_category(state: State, args: argparse.Namespace) -> None:
    tx = ensure_transaction(state, args.transaction)
    ensure_category(state, args.category)
    tx["category"] = args.category
    print("ok")


def cmd_list_transactions(state: State, args: argparse.Namespace) -> None:
    rows = []
    for tx in state["transactions"].values():
        if args.account and tx.get("account") != args.account:
            continue
        if args.category and tx.get("category") != args.category:
            continue
        if args.payee and tx.get("payee") != args.payee:
            continue
        if args.month and month_of(tx.get("date", "")) != args.month:
            continue
        rows.append(copy.deepcopy(tx))
    rows.sort(key=lambda x: (x.get("date", ""), x.get("id", "")))
    print_json(rows)


def cmd_report(state: State, args: argparse.Namespace) -> None:
    print_json(report_for_month(state, validate_month(args.month)))


def cmd_state(state: State, args: argparse.Namespace) -> None:
    print_json(public_state(state))


def cmd_create_rule(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        raise BudgetMiniError("rule name is required")
    if args.name in state["rules"]:
        raise BudgetMiniError(f"rule already exists: {args.name}")
    if args.field != "payee":
        raise BudgetMiniError("only payee field rules are supported")
    ensure_category(state, args.set_category)
    state["rules"][args.name] = {
        "name": args.name,
        "condition": {"field": args.field, "equals": args.equals},
        "action": {"set_category": args.set_category},
    }
    print("ok")


def cmd_apply_rules(state: State, args: argparse.Namespace) -> None:
    for tx in state["transactions"].values():
        apply_rules_to_transaction(state, tx)
    print("ok")


def cmd_create_schedule(state: State, args: argparse.Namespace) -> None:
    if not args.name:
        raise BudgetMiniError("schedule name is required")
    if args.name in state["schedules"]:
        raise BudgetMiniError(f"schedule already exists: {args.name}")
    ensure_account(state, args.account)
    ensure_category(state, args.category)
    amt = money(args.amount, "amount")
    if amt <= 0:
        raise BudgetMiniError("amount must be greater than 0")
    if args.direction not in ("payment", "deposit"):
        raise BudgetMiniError("direction must be payment or deposit")
    if args.repeat not in ("none", "monthly"):
        raise BudgetMiniError("repeat must be none or monthly")
    if args.day < 1 or args.day > 31:
        raise BudgetMiniError("day must be between 1 and 31")
    state["schedules"][args.name] = {
        "id": args.name,
        "name": args.name,
        "payee": args.payee or "",
        "account": args.account,
        "category": args.category,
        "amount": money_out(amt),
        "direction": args.direction,
        "repeat": args.repeat,
        "day": args.day,
        "can_generate": True,
        "generated_transactions": [],
    }
    add_payee_if_needed(state, args.payee)
    print("ok")


def cmd_generate_scheduled_transaction(state: State, args: argparse.Namespace) -> None:
    if args.schedule not in state["schedules"]:
        raise BudgetMiniError(f"schedule not found: {args.schedule}")
    if args.id in state["transactions"]:
        raise BudgetMiniError(f"transaction already exists: {args.id}")
    sched = state["schedules"][args.schedule]
    if not sched.get("can_generate", True):
        raise BudgetMiniError("schedule cannot generate a transaction")
    amt = sched.get("amount", 0)
    payment = amt if sched.get("direction") == "payment" else 0
    deposit = amt if sched.get("direction") == "deposit" else 0
    tx = build_transaction(
        state,
        txid=args.id,
        date=args.date,
        account=sched.get("account"),
        payee=sched.get("payee"),
        notes=f"Generated from schedule: {args.schedule}",
        category=sched.get("category"),
        payment=payment,
        deposit=deposit,
        tags=[],
        schedule=args.schedule,
    )
    apply_rules_to_transaction(state, tx)
    state["transactions"][args.id] = tx
    sched.setdefault("generated_transactions", []).append(args.id)
    add_payee_if_needed(state, tx.get("payee"))
    print("ok")


def cmd_assign_tag(state: State, args: argparse.Namespace) -> None:
    tx = ensure_transaction(state, args.transaction)
    if not args.tag:
        raise BudgetMiniError("tag is required")
    tags = tx.setdefault("tags", [])
    if args.tag not in tags:
        tags.append(args.tag)
    add_tag_if_needed(state, args.tag)
    print("ok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budgetmini.py")
    parser.add_argument("data_file")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-account")
    p.add_argument("--name", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--on-budget", action="store_true")
    p.add_argument("--off-budget", dest="on_budget", action="store_false")
    p.set_defaults(func=cmd_create_account)

    p = sub.add_parser("rename-account")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(func=cmd_rename_account)

    p = sub.add_parser("list-accounts")
    p.set_defaults(func=cmd_list_accounts, readonly=True)

    p = sub.add_parser("create-category-group")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_category_group)

    p = sub.add_parser("rename-category-group")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(func=cmd_rename_category_group)

    p = sub.add_parser("create-category")
    p.add_argument("--group", required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_create_category)

    p = sub.add_parser("rename-category")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(func=cmd_rename_category)

    p = sub.add_parser("set-budget")
    p.add_argument("--month", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--amount", required=True)
    p.set_defaults(func=cmd_set_budget)

    p = sub.add_parser("show-budget")
    p.add_argument("--month", required=True)
    p.set_defaults(func=cmd_show_budget, readonly=True)

    p = sub.add_parser("add-transaction")
    p.add_argument("--id", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--account", required=True)
    p.add_argument("--payee", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--category", default="")
    p.add_argument("--payment", default="0")
    p.add_argument("--deposit", default="0")
    p.add_argument("--tags", nargs="*", default=[])
    p.set_defaults(func=cmd_add_transaction)

    p = sub.add_parser("edit-transaction")
    p.add_argument("--id", required=True)
    p.add_argument("--date")
    p.add_argument("--account")
    p.add_argument("--payee")
    p.add_argument("--notes")
    p.add_argument("--category")
    p.add_argument("--payment")
    p.add_argument("--deposit")
    p.add_argument("--tags", nargs="*")
    p.set_defaults(func=cmd_edit_transaction)

    p = sub.add_parser("delete-transaction")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_delete_transaction)

    p = sub.add_parser("assign-category")
    p.add_argument("--transaction", required=True)
    p.add_argument("--category", required=True)
    p.set_defaults(func=cmd_assign_category)

    p = sub.add_parser("list-transactions")
    p.add_argument("--account")
    p.add_argument("--category")
    p.add_argument("--payee")
    p.add_argument("--month")
    p.set_defaults(func=cmd_list_transactions, readonly=True)

    p = sub.add_parser("report")
    p.add_argument("--month", required=True)
    p.set_defaults(func=cmd_report, readonly=True)

    p = sub.add_parser("state")
    p.set_defaults(func=cmd_state, readonly=True)

    p = sub.add_parser("create-rule")
    p.add_argument("--name", required=True)
    p.add_argument("--field", required=True)
    p.add_argument("--equals", required=True)
    p.add_argument("--set-category", required=True)
    p.set_defaults(func=cmd_create_rule)

    p = sub.add_parser("apply-rules")
    p.set_defaults(func=cmd_apply_rules)

    p = sub.add_parser("create-schedule")
    p.add_argument("--name", required=True)
    p.add_argument("--payee", required=True)
    p.add_argument("--account", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--direction", choices=["payment", "deposit"], required=True)
    p.add_argument("--repeat", choices=["none", "monthly"], default="monthly")
    p.add_argument("--day", type=int, required=True)
    p.set_defaults(func=cmd_create_schedule)

    p = sub.add_parser("generate-scheduled-transaction")
    p.add_argument("--schedule", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_generate_scheduled_transaction)

    p = sub.add_parser("assign-tag")
    p.add_argument("--transaction", required=True)
    p.add_argument("--tag", required=True)
    p.set_defaults(func=cmd_assign_tag)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        state = load_state(args.data_file)
        working = copy.deepcopy(state)
        args.func(working, args)
        if not getattr(args, "readonly", False):
            save_state(args.data_file, working)
        return 0
    except BudgetMiniError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
