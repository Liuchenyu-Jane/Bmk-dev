#!/usr/bin/env python3
"""
budgetmini.py - A simplified personal finance system based on Actual Budget.
"""

import json
import os
import sys
import argparse
from datetime import datetime
from collections import defaultdict
from copy import deepcopy


class BudgetMini:
    def __init__(self, data_file):
        self.data_file = data_file
        self.data = self._load_data()

    def _load_data(self):
        """Load data from JSON file or create new empty state."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        return self._create_empty_state()

    def _create_empty_state(self):
        """Create an empty financial state."""
        return {
            "accounts": {},
            "transactions": {},
            "category_groups": {},
            "categories": {},
            "budgets": {},
            "rules": {},
            "schedules": {},
            "payees": {},
            "tags": {}
        }

    def _save_data(self):
        """Save data to JSON file."""
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def _calculate_account_balance(self, account_name):
        """Calculate balance for a specific account from transactions."""
        balance = 0.0
        for tx in self.data["transactions"].values():
            if tx.get("account") == account_name:
                balance += tx.get("deposit", 0) - tx.get("payment", 0)
        return balance

    def _calculate_category_spending(self, category_name, year_month):
        """Calculate spending for a category in a specific month."""
        spending = 0.0
        for tx in self.data["transactions"].values():
            if tx.get("category") == category_name and tx.get("date", "").startswith(year_month):
                spending += tx.get("payment", 0)
        return spending

    def _calculate_total_income(self, year_month):
        """Calculate total income for a month."""
        income = 0.0
        for tx in self.data["transactions"].values():
            if tx.get("date", "").startswith(year_month):
                income += tx.get("deposit", 0)
        return income

    def _calculate_total_expenses(self, year_month):
        """Calculate total expenses for a month."""
        expenses = 0.0
        for tx in self.data["transactions"].values():
            if tx.get("date", "").startswith(year_month):
                expenses += tx.get("payment", 0)
        return expenses

    def _calculate_net_worth(self):
        """Calculate net worth from all accounts."""
        net_worth = 0.0
        for account_name in self.data["accounts"]:
            net_worth += self._calculate_account_balance(account_name)
        return net_worth

    def _update_budget_spending(self, year_month, category_name):
        """Update budget spent amount for a category."""
        if year_month not in self.data["budgets"]:
            return
        if category_name not in self.data["budgets"][year_month]:
            return
        
        spent = self._calculate_category_spending(category_name, year_month)
        budgeted = self.data["budgets"][year_month][category_name].get("budgeted", 0)
        self.data["budgets"][year_month][category_name]["spent"] = spent
        self.data["budgets"][year_month][category_name]["balance"] = budgeted - spent

    def _update_all_budgets(self):
        """Update all budget spending values."""
        for year_month in self.data["budgets"]:
            for category_name in self.data["budgets"][year_month]:
                self._update_budget_spending(year_month, category_name)

    def _get_payee_name(self, payee):
        """Get or create payee name."""
        if payee and payee not in self.data["payees"]:
            self.data["payees"][payee] = {"name": payee}
        return payee

    def _apply_rules_to_transaction(self, transaction):
        """Apply rules to a transaction."""
        for rule in self.data["rules"].values():
            if rule.get("field") == "payee" and rule.get("equals"):
                if transaction.get("payee") == rule["equals"]:
                    if rule.get("set_category"):
                        transaction["category"] = rule["set_category"]
        return transaction

    # ==================== Account Commands ====================

    def create_account(self, name, account_type, on_budget):
        """Create a new account."""
        if name in self.data["accounts"]:
            return False, f"Account '{name}' already exists"
        
        self.data["accounts"][name] = {
            "name": name,
            "type": account_type,
            "on_budget": on_budget,
            "balance": 0
        }
        self._save_data()
        return True, "ok"

    def rename_account(self, old_name, new_name):
        """Rename an existing account."""
        if old_name not in self.data["accounts"]:
            return False, f"Account '{old_name}' does not exist"
        if new_name in self.data["accounts"]:
            return False, f"Account '{new_name}' already exists"
        
        # Update account
        self.data["accounts"][new_name] = self.data["accounts"].pop(old_name)
        self.data["accounts"][new_name]["name"] = new_name
        
        # Update transactions
        for tx in self.data["transactions"].values():
            if tx.get("account") == old_name:
                tx["account"] = new_name
        
        # Update schedules
        for schedule in self.data["schedules"].values():
            if schedule.get("account") == old_name:
                schedule["account"] = new_name
        
        self._save_data()
        return True, "ok"

    def list_accounts(self):
        """List all accounts with their balances."""
        result = {}
        for name, account in self.data["accounts"].items():
            balance = self._calculate_account_balance(name)
            result[name] = {
                "name": name,
                "type": account["type"],
                "on_budget": account["on_budget"],
                "balance": balance
            }
        return True, result

    # ==================== Category Commands ====================

    def create_category_group(self, name):
        """Create a new category group."""
        if name in self.data["category_groups"]:
            return False, f"Category group '{name}' already exists"
        
        self.data["category_groups"][name] = {
            "name": name,
            "categories": []
        }
        self._save_data()
        return True, "ok"

    def rename_category_group(self, old_name, new_name):
        """Rename a category group."""
        if old_name not in self.data["category_groups"]:
            return False, f"Category group '{old_name}' does not exist"
        if new_name in self.data["category_groups"]:
            return False, f"Category group '{new_name}' already exists"
        
        self.data["category_groups"][new_name] = self.data["category_groups"].pop(old_name)
        self.data["category_groups"][new_name]["name"] = new_name
        
        # Update categories
        for category in self.data["categories"].values():
            if category.get("group") == old_name:
                category["group"] = new_name
        
        self._save_data()
        return True, "ok"

    def create_category(self, group_name, category_name):
        """Create a new category under a group."""
        if group_name not in self.data["category_groups"]:
            return False, f"Category group '{group_name}' does not exist"
        if category_name in self.data["categories"]:
            return False, f"Category '{category_name}' already exists"
        
        self.data["categories"][category_name] = {
            "name": category_name,
            "group": group_name
        }
        self.data["category_groups"][group_name]["categories"].append(category_name)
        self._save_data()
        return True, "ok"

    def rename_category(self, old_name, new_name):
        """Rename a category."""
        if old_name not in self.data["categories"]:
            return False, f"Category '{old_name}' does not exist"
        if new_name in self.data["categories"]:
            return False, f"Category '{new_name}' already exists"
        
        # Update category
        self.data["categories"][new_name] = self.data["categories"].pop(old_name)
        self.data["categories"][new_name]["name"] = new_name
        
        # Update group reference
        group_name = self.data["categories"][new_name]["group"]
        categories_list = self.data["category_groups"][group_name]["categories"]
        categories_list = [new_name if c == old_name else c for c in categories_list]
        self.data["category_groups"][group_name]["categories"] = categories_list
        
        # Update transactions
        for tx in self.data["transactions"].values():
            if tx.get("category") == old_name:
                tx["category"] = new_name
        
        # Update budgets
        for year_month in self.data["budgets"]:
            if old_name in self.data["budgets"][year_month]:
                self.data["budgets"][year_month][new_name] = self.data["budgets"][year_month].pop(old_name)
        
        # Update rules
        for rule in self.data["rules"].values():
            if rule.get("set_category") == old_name:
                rule["set_category"] = new_name
        
        # Update schedules
        for schedule in self.data["schedules"].values():
            if schedule.get("category") == old_name:
                schedule["category"] = new_name
        
        self._update_all_budgets()
        self._save_data()
        return True, "ok"

    # ==================== Budget Commands ====================

    def set_budget(self, year_month, category_name, amount):
        """Set budget amount for a category in a specific month."""
        if category_name not in self.data["categories"]:
            return False, f"Category '{category_name}' does not exist"
        
        if year_month not in self.data["budgets"]:
            self.data["budgets"][year_month] = {}
        
        spent = self._calculate_category_spending(category_name, year_month)
        self.data["budgets"][year_month][category_name] = {
            "budgeted": amount,
            "spent": spent,
            "balance": amount - spent
        }
        self._save_data()
        return True, "ok"

    def show_budget(self, year_month):
        """Show budget for a specific month."""
        result = {}
        if year_month in self.data["budgets"]:
            for category_name, budget in self.data["budgets"][year_month].items():
                result[category_name] = {
                    "budgeted": budget["budgeted"],
                    "spent": budget["spent"],
                    "balance": budget["balance"]
                }
        return True, result

    # ==================== Transaction Commands ====================

    def add_transaction(self, tx_id, date_str, account, payee, category, payment, deposit, notes=""):
        """Add a new transaction."""
        # Validation
        if not account:
            return False, "account is required"
        if account not in self.data["accounts"]:
            return False, f"Account '{account}' does not exist"
        if payment > 0 and deposit > 0:
            return False, "transaction cannot have both payment and deposit"
        if payment == 0 and deposit == 0:
            return False, "transaction must have either payment or deposit"
        if tx_id in self.data["transactions"]:
            return False, f"Transaction '{tx_id}' already exists"
        if category and category not in self.data["categories"]:
            return False, f"Category '{category}' does not exist"
        
        # Validate date format
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return False, "date must be in YYYY-MM-DD format"
        
        year_month = date_str[:7]
        
        # Create transaction
        transaction = {
            "id": tx_id,
            "date": date_str,
            "account": account,
            "payee": self._get_payee_name(payee) if payee else "",
            "notes": notes,
            "category": category or "",
            "payment": float(payment),
            "deposit": float(deposit),
            "tags": []
        }
        
        # Apply rules
        transaction = self._apply_rules_to_transaction(transaction)
        
        self.data["transactions"][tx_id] = transaction
        
        # Update budget
        if transaction["category"] and year_month:
            self._update_budget_spending(year_month, transaction["category"])
        
        self._save_data()
        return True, "ok"

    def edit_transaction(self, tx_id, **kwargs):
        """Edit an existing transaction."""
        if tx_id not in self.data["transactions"]:
            return False, f"Transaction '{tx_id}' does not exist"
        
        old_tx = self.data["transactions"][tx_id].copy()
        
        # Validate payment/deposit conflict
        new_payment = kwargs.get("payment", old_tx["payment"])
        new_deposit = kwargs.get("deposit", old_tx["deposit"])
        if new_payment > 0 and new_deposit > 0:
            return False, "transaction cannot have both payment and deposit"
        
        # Update fields
        for key, value in kwargs.items():
            if value is not None and key in ["date", "account", "payee", "notes", "category", "payment", "deposit"]:
                if key == "payee" and value:
                    value = self._get_payee_name(value)
                self.data["transactions"][tx_id][key] = value
        
        # Update budgets for affected months
        old_year_month = old_tx["date"][:7] if old_tx["date"] else None
        new_year_month = self.data["transactions"][tx_id]["date"][:7] if self.data["transactions"][tx_id]["date"] else None
        
        if old_tx["category"]:
            self._update_budget_spending(old_year_month, old_tx["category"])
        if self.data["transactions"][tx_id]["category"]:
            self._update_budget_spending(new_year_month, self.data["transactions"][tx_id]["category"])
        
        self._save_data()
        return True, "ok"

    def delete_transaction(self, tx_id):
        """Delete a transaction."""
        if tx_id not in self.data["transactions"]:
            return False, f"Transaction '{tx_id}' does not exist"
        
        tx = self.data["transactions"][tx_id]
        year_month = tx["date"][:7] if tx["date"] else None
        
        del self.data["transactions"][tx_id]
        
        if tx.get("category") and year_month:
            self._update_budget_spending(year_month, tx["category"])
        
        self._save_data()
        return True, "ok"

    def assign_category(self, tx_id, category_name):
        """Assign a category to a transaction."""
        if tx_id not in self.data["transactions"]:
            return False, f"Transaction '{tx_id}' does not exist"
        if category_name not in self.data["categories"]:
            return False, f"Category '{category_name}' does not exist"
        
        old_tx = self.data["transactions"][tx_id].copy()
        self.data["transactions"][tx_id]["category"] = category_name
        
        # Update budgets
        old_year_month = old_tx["date"][:7] if old_tx["date"] else None
        new_year_month = self.data["transactions"][tx_id]["date"][:7]
        
        if old_tx.get("category"):
            self._update_budget_spending(old_year_month, old_tx["category"])
        self._update_budget_spending(new_year_month, category_name)
        
        self._save_data()
        return True, "ok"

    def list_transactions(self, account=None, category=None, payee=None, month=None):
        """List transactions with optional filters."""
        result = {}
        for tx_id, tx in self.data["transactions"].items():
            if account and tx.get("account") != account:
                continue
            if category and tx.get("category") != category:
                continue
            if payee and tx.get("payee") != payee:
                continue
            if month and not tx.get("date", "").startswith(month):
                continue
            result[tx_id] = tx
        
        return True, result

    # ==================== Report Commands ====================

    def report(self, year_month):
        """Generate report for a specific month."""
        total_income = self._calculate_total_income(year_month)
        total_expenses = self._calculate_total_expenses(year_month)
        net_worth = self._calculate_net_worth()
        cash_flow = total_income - total_expenses
        
        # Calculate averages
        months = set()
        for tx in self.data["transactions"].values():
            if tx.get("date"):
                months.add(tx["date"][:7])
        
        num_months = len(months)
        avg_per_month = (total_income + total_expenses) / num_months if num_months > 0 else 0
        
        num_transactions = len(self.data["transactions"])
        avg_per_transaction = (total_income + total_expenses) / num_transactions if num_transactions > 0 else 0
        
        result = {
            "month": year_month,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_worth": net_worth,
            "cash_flow": cash_flow,
            "average_per_month": avg_per_month,
            "average_per_transaction": avg_per_transaction
        }
        
        # Budget overview
        budget_overview = {}
        if year_month in self.data["budgets"]:
            for category, budget in self.data["budgets"][year_month].items():
                if budget["balance"] < 0:
                    budget_overview[category] = "overspent"
                elif budget["balance"] == 0:
                    budget_overview[category] = "on_track"
                else:
                    budget_overview[category] = "under_budget"
        
        result["budget_overview"] = budget_overview
        
        return True, result

    def get_state(self):
        """Get full system state with recalculated values."""
        state = deepcopy(self.data)
        
        # Update account balances
        for account_name in state["accounts"]:
            state["accounts"][account_name]["balance"] = self._calculate_account_balance(account_name)
        
        # Update budget spent amounts
        self._update_all_budgets()
        
        # Add reports
        state["reports"] = {}
        for year_month in self.data["budgets"]:
            _, report = self.report(year_month)
            state["reports"][year_month] = report
        
        return True, state

    # ==================== Rule Commands ====================

    def create_rule(self, name, field, equals, set_category):
        """Create a new rule."""
        if name in self.data["rules"]:
            return False, f"Rule '{name}' already exists"
        
        if field != "payee":
            return False, "Only payee field is supported for conditions"
        
        self.data["rules"][name] = {
            "name": name,
            "field": field,
            "equals": equals,
            "set_category": set_category
        }
        self._save_data()
        return True, "ok"

    def apply_rules(self):
        """Apply all rules to all transactions."""
        for tx_id, tx in self.data["transactions"].items():
            old_category = tx.get("category")
            tx = self._apply_rules_to_transaction(tx)
            if old_category != tx.get("category"):
                if old_category:
                    year_month = tx["date"][:7]
                    self._update_budget_spending(year_month, old_category)
                if tx.get("category"):
                    year_month = tx["date"][:7]
                    self._update_budget_spending(year_month, tx["category"])
        
        self._save_data()
        return True, "ok"

    # ==================== Schedule Commands ====================

    def create_schedule(self, name, payee, account, category, amount, direction, repeat, day):
        """Create a new schedule."""
        if name in self.data["schedules"]:
            return False, f"Schedule '{name}' already exists"
        
        if account not in self.data["accounts"]:
            return False, f"Account '{account}' does not exist"
        if category and category not in self.data["categories"]:
            return False, f"Category '{category}' does not exist"
        
        self.data["schedules"][name] = {
            "name": name,
            "payee": self._get_payee_name(payee),
            "account": account,
            "category": category,
            "amount": float(amount),
            "direction": direction,
            "repeat": repeat,
            "day": int(day)
        }
        self._save_data()
        return True, "ok"

    def generate_scheduled_transaction(self, schedule_name, date_str, tx_id):
        """Generate a transaction from a schedule."""
        if schedule_name not in self.data["schedules"]:
            return False, f"Schedule '{schedule_name}' does not exist"
        if tx_id in self.data["transactions"]:
            return False, f"Transaction '{tx_id}' already exists"
        
        schedule = self.data["schedules"][schedule_name]
        
        payment = schedule["amount"] if schedule["direction"] == "payment" else 0
        deposit = schedule["amount"] if schedule["direction"] == "deposit" else 0
        
        return self.add_transaction(
            tx_id=tx_id,
            date_str=date_str,
            account=schedule["account"],
            payee=schedule["payee"],
            category=schedule["category"],
            payment=payment,
            deposit=deposit
        )

    # ==================== Tag Commands ====================

    def assign_tag(self, tx_id, tag):
        """Assign a tag to a transaction."""
        if tx_id not in self.data["transactions"]:
            return False, f"Transaction '{tx_id}' does not exist"
        
        if tag not in self.data["tags"]:
            self.data["tags"][tag] = {"name": tag}
        
        if tag not in self.data["transactions"][tx_id]["tags"]:
            self.data["transactions"][tx_id]["tags"].append(tag)
        
        self._save_data()
        return True, "ok"


def main():
    parser = argparse.ArgumentParser(description="Actual Budget Mini Finance Tool")
    parser.add_argument("data_file", help="JSON data file path")
    parser.add_argument("command", help="Command to execute")
    
    # Parse known args first, then handle remaining
    args, remaining = parser.parse_known_args()
    
    budget = BudgetMini(args.data_file)
    success = True
    result = None
    error_msg = None
    
    # Account commands
    if args.command == "create-account":
        parser = argparse.ArgumentParser()
        parser.add_argument("--name", required=True)
        parser.add_argument("--type", required=True)
        parser.add_argument("--on-budget", action="store_true")
        sub_args = parser.parse_args(remaining)
        success, result = budget.create_account(sub_args.name, sub_args.type, sub_args.on_budget)
    
    elif args.command == "rename-account":
        parser = argparse.ArgumentParser()
        parser.add_argument("--old", required=True)
        parser.add_argument("--new", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.rename_account(sub_args.old, sub_args.new)
    
    elif args.command == "list-accounts":
        success, result = budget.list_accounts()
    
    # Category commands
    elif args.command == "create-category-group":
        parser = argparse.ArgumentParser()
        parser.add_argument("--name", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.create_category_group(sub_args.name)
    
    elif args.command == "rename-category-group":
        parser = argparse.ArgumentParser()
        parser.add_argument("--old", required=True)
        parser.add_argument("--new", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.rename_category_group(sub_args.old, sub_args.new)
    
    elif args.command == "create-category":
        parser = argparse.ArgumentParser()
        parser.add_argument("--group", required=True)
        parser.add_argument("--name", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.create_category(sub_args.group, sub_args.name)
    
    elif args.command == "rename-category":
        parser = argparse.ArgumentParser()
        parser.add_argument("--old", required=True)
        parser.add_argument("--new", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.rename_category(sub_args.old, sub_args.new)
    
    # Budget commands
    elif args.command == "set-budget":
        parser = argparse.ArgumentParser()
        parser.add_argument("--month", required=True)
        parser.add_argument("--category", required=True)
        parser.add_argument("--amount", type=float, required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.set_budget(sub_args.month, sub_args.category, sub_args.amount)
    
    elif args.command == "show-budget":
        parser = argparse.ArgumentParser()
        parser.add_argument("--month", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.show_budget(sub_args.month)
    
    # Transaction commands
    elif args.command == "add-transaction":
        parser = argparse.ArgumentParser()
        parser.add_argument("--id", required=True)
        parser.add_argument("--date", required=True)
        parser.add_argument("--account", required=True)
        parser.add_argument("--payee", default="")
        parser.add_argument("--category", default="")
        parser.add_argument("--payment", type=float, default=0)
        parser.add_argument("--deposit", type=float, default=0)
        parser.add_argument("--notes", default="")
        sub_args = parser.parse_args(remaining)
        success, result = budget.add_transaction(
            sub_args.id, sub_args.date, sub_args.account,
            sub_args.payee, sub_args.category, sub_args.payment,
            sub_args.deposit, sub_args.notes
        )
    
    elif args.command == "edit-transaction":
        parser = argparse.ArgumentParser()
        parser.add_argument("--id", required=True)
        parser.add_argument("--date")
        parser.add_argument("--account")
        parser.add_argument("--payee")
        parser.add_argument("--category")
        parser.add_argument("--payment", type=float)
        parser.add_argument("--deposit", type=float)
        parser.add_argument("--notes")
        sub_args = parser.parse_args(remaining)
        kwargs = {k: v for k, v in vars(sub_args).items() if v is not None and k != "id"}
        success, result = budget.edit_transaction(sub_args.id, **kwargs)
    
    elif args.command == "delete-transaction":
        parser = argparse.ArgumentParser()
        parser.add_argument("--id", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.delete_transaction(sub_args.id)
    
    elif args.command == "assign-category":
        parser = argparse.ArgumentParser()
        parser.add_argument("--transaction", required=True)
        parser.add_argument("--category", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.assign_category(sub_args.transaction, sub_args.category)
    
    elif args.command == "list-transactions":
        parser = argparse.ArgumentParser()
        parser.add_argument("--account")
        parser.add_argument("--category")
        parser.add_argument("--payee")
        parser.add_argument("--month")
        sub_args = parser.parse_args(remaining)
        success, result = budget.list_transactions(
            sub_args.account, sub_args.category, sub_args.payee, sub_args.month
        )
    
    # Report commands
    elif args.command == "report":
        parser = argparse.ArgumentParser()
        parser.add_argument("--month", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.report(sub_args.month)
    
    elif args.command == "state":
        success, result = budget.get_state()
    
    # Rule commands
    elif args.command == "create-rule":
        parser = argparse.ArgumentParser()
        parser.add_argument("--name", required=True)
        parser.add_argument("--field", required=True)
        parser.add_argument("--equals", required=True)
        parser.add_argument("--set-category", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.create_rule(
            sub_args.name, sub_args.field, sub_args.equals, sub_args.set_category
        )
    
    elif args.command == "apply-rules":
        success, result = budget.apply_rules()
    
    # Schedule commands
    elif args.command == "create-schedule":
        parser = argparse.ArgumentParser()
        parser.add_argument("--name", required=True)
        parser.add_argument("--payee", required=True)
        parser.add_argument("--account", required=True)
        parser.add_argument("--category", required=True)
        parser.add_argument("--amount", type=float, required=True)
        parser.add_argument("--direction", required=True, choices=["payment", "deposit"])
        parser.add_argument("--repeat", required=True)
        parser.add_argument("--day", type=int, required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.create_schedule(
            sub_args.name, sub_args.payee, sub_args.account,
            sub_args.category, sub_args.amount, sub_args.direction,
            sub_args.repeat, sub_args.day
        )
    
    elif args.command == "generate-scheduled-transaction":
        parser = argparse.ArgumentParser()
        parser.add_argument("--schedule", required=True)
        parser.add_argument("--date", required=True)
        parser.add_argument("--id", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.generate_scheduled_transaction(
            sub_args.schedule, sub_args.date, sub_args.id
        )
    
    # Tag commands
    elif args.command == "assign-tag":
        parser = argparse.ArgumentParser()
        parser.add_argument("--transaction", required=True)
        parser.add_argument("--tag", required=True)
        sub_args = parser.parse_args(remaining)
        success, result = budget.assign_tag(sub_args.transaction, sub_args.tag)
    
    else:
        success = False
        error_msg = f"Unknown command: {args.command}"
    
    if not success:
        print(error_msg or result, file=sys.stderr)
        sys.exit(1)
    
    # Output result
    if isinstance(result, dict):
        print(json.dumps(result, indent=2))
    else:
        print(result)


if __name__ == "__main__":
    main()