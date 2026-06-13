import argparse
import json
import sys
import os
from datetime import datetime

# --------------------------
# 数据初始化与存储
# --------------------------
def init_data():
    """初始化空的财务数据结构"""
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

def load_data(file_path):
    """加载JSON数据文件，不存在则创建初始数据"""
    if not os.path.exists(file_path):
        return init_data()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("error: invalid JSON in data file", file=sys.stderr)
        sys.exit(1)

def save_data(file_path, data):
    """保存数据到JSON文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"error: failed to save data - {str(e)}", file=sys.stderr)
        sys.exit(1)

# --------------------------
# 辅助计算函数（保障状态一致性）
# --------------------------
def calculate_account_balance(data, account_name):
    """计算账户余额：总存款 - 总支出"""
    transactions = data["transactions"].values()
    total_deposit = 0.0
    total_payment = 0.0
    for tx in transactions:
        if tx["account"] == account_name:
            total_deposit += float(tx["deposit"])
            total_payment += float(tx["payment"])
    return total_deposit - total_payment

def calculate_category_monthly_spent(data, category_name, month):
    """计算分类月度支出"""
    transactions = data["transactions"].values()
    spent = 0.0
    for tx in transactions:
        if tx["date"].startswith(month) and tx["category"] == category_name:
            spent += float(tx["payment"])
    return spent

def calculate_budget_balance(budgeted, spent):
    """计算预算余额：预算金额 - 已支出金额"""
    return budgeted - spent

def calculate_report_data(data, month):
    """计算月度报表数据"""
    transactions = data["transactions"].values()
    total_income = 0.0
    total_expenses = 0.0
    
    # 计算收支总额
    for tx in transactions:
        if tx["date"].startswith(month):
            total_income += float(tx["deposit"])
            total_expenses += float(tx["payment"])
    
    # 计算净资产（所有账户余额总和）
    net_worth = 0.0
    for account in data["accounts"].values():
        net_worth += float(account["balance"])
    
    cash_flow = total_income - total_expenses
    return {
        "month": month,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_worth": net_worth,
        "cash_flow": cash_flow
    }

# --------------------------
# 账户管理命令处理
# --------------------------
def handle_create_account(args, data):
    """创建新账户"""
    account_name = args.name
    if account_name in data["accounts"]:
        print(f"error: account '{account_name}' already exists", file=sys.stderr)
        sys.exit(1)
    
    data["accounts"][account_name] = {
        "name": account_name,
        "type": args.type,
        "on_budget": args.on_budget,
        "balance": 0.0
    }
    return "ok"

def handle_rename_account(args, data):
    """重命名账户（同步更新关联交易）"""
    old_name = args.old
    new_name = args.new
    
    if old_name not in data["accounts"]:
        print(f"error: account '{old_name}' does not exist", file=sys.stderr)
        sys.exit(1)
    if new_name in data["accounts"]:
        print(f"error: account '{new_name}' already exists", file=sys.stderr)
        sys.exit(1)
    
    # 重命名账户
    account = data["accounts"].pop(old_name)
    account["name"] = new_name
    data["accounts"][new_name] = account
    
    # 更新关联交易
    for tx in data["transactions"].values():
        if tx["account"] == old_name:
            tx["account"] = new_name
    
    # 重新计算余额
    new_balance = calculate_account_balance(data, new_name)
    data["accounts"][new_name]["balance"] = new_balance
    return "ok"

def handle_list_accounts(args, data):
    """列出所有账户（JSON格式）"""
    accounts = list(data["accounts"].values())
    print(json.dumps(accounts, indent=2))

# --------------------------
# 分类组/分类管理命令处理
# --------------------------
def handle_create_category_group(args, data):
    """创建分类组"""
    group_name = args.name
    if group_name in data["category_groups"]:
        print(f"error: category group '{group_name}' already exists", file=sys.stderr)
        sys.exit(1)
    
    data["category_groups"][group_name] = {
        "name": group_name,
        "categories": []
    }
    return "ok"

def handle_rename_category_group(args, data):
    """重命名分类组（同步更新关联分类）"""
    old_name = args.old
    new_name = args.new
    
    if old_name not in data["category_groups"]:
        print(f"error: category group '{old_name}' does not exist", file=sys.stderr)
        sys.exit(1)
    if new_name in data["category_groups"]:
        print(f"error: category group '{new_name}' already exists", file=sys.stderr)
        sys.exit(1)
    
    # 重命名分类组
    group = data["category_groups"].pop(old_name)
    group["name"] = new_name
    data["category_groups"][new_name] = group
    
    # 更新关联分类
    for cat in data["categories"].values():
        if cat["group"] == old_name:
            cat["group"] = new_name
    return "ok"

def handle_create_category(args, data):
    """在分类组下创建分类"""
    group_name = args.group
    cat_name = args.name
    
    if group_name not in data["category_groups"]:
        print(f"error: category group '{group_name}' does not exist", file=sys.stderr)
        sys.exit(1)
    if cat_name in data["categories"]:
        print(f"error: category '{cat_name}' already exists", file=sys.stderr)
        sys.exit(1)
    
    # 创建分类
    data["categories"][cat_name] = {
        "name": cat_name,
        "group": group_name
    }
    # 更新分类组的分类列表
    data["category_groups"][group_name]["categories"].append(cat_name)
    return "ok"

def handle_rename_category(args, data):
    """重命名分类（同步更新关联交易/预算）"""
    old_name = args.old
    new_name = args.new
    
    if old_name not in data["categories"]:
        print(f"error: category '{old_name}' does not exist", file=sys.stderr)
        sys.exit(1)
    if new_name in data["categories"]:
        print(f"error: category '{new_name}' already exists", file=sys.stderr)
        sys.exit(1)
    
    # 重命名分类
    cat = data["categories"].pop(old_name)
    cat["name"] = new_name
    data["categories"][new_name] = cat
    
    # 更新分类组的分类列表
    group_name = cat["group"]
    data["category_groups"][group_name]["categories"] = [
        new_name if c == old_name else c 
        for c in data["category_groups"][group_name]["categories"]
    ]
    
    # 更新关联交易
    for tx in data["transactions"].values():
        if tx["category"] == old_name:
            tx["category"] = new_name
    
    # 更新关联预算
    for month in data["budgets"]:
        if old_name in data["budgets"][month]:
            budget = data["budgets"][month].pop(old_name)
            data["budgets"][month][new_name] = budget
            # 重新计算预算数据
            spent = calculate_category_monthly_spent(data, new_name, month)
            data["budgets"][month][new_name]["spent"] = spent
            data["budgets"][month][new_name]["balance"] = calculate_budget_balance(
                data["budgets"][month][new_name]["budgeted"], spent
            )
    return "ok"

# --------------------------
# 预算管理命令处理
# --------------------------
def handle_set_budget(args, data):
    """设置分类月度预算"""
    month = args.month
    category = args.category
    amount = float(args.amount)
    
    # 验证参数
    if category not in data["categories"]:
        print(f"error: category '{category}' does not exist", file=sys.stderr)
        sys.exit(1)
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        print("error: invalid month format, use YYYY-MM", file=sys.stderr)
        sys.exit(1)
    
    # 初始化月度预算
    if month not in data["budgets"]:
        data["budgets"][month] = {}
    
    # 计算分类月度支出并设置预算
    spent = calculate_category_monthly_spent(data, category, month)
    data["budgets"][month][category] = {
        "budgeted": amount,
        "spent": spent,
        "balance": calculate_budget_balance(amount, spent)
    }
    return "ok"

def handle_show_budget(args, data):
    """展示月度预算（JSON格式）"""
    month = args.month
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        print("error: invalid month format, use YYYY-MM", file=sys.stderr)
        sys.exit(1)
    
    budget_data = data["budgets"].get(month, {})
    output = {
        "month": month,
        "categories": budget_data
    }
    print(json.dumps(output, indent=2))

# --------------------------
# 交易管理命令处理
# --------------------------
def handle_add_transaction(args, data):
    """添加新交易（验证参数+更新关联数据）"""
    tx_id = args.id
    date = args.date
    account = args.account
    payee = args.payee
    category = args.category
    payment = float(args.payment)
    deposit = float(args.deposit)
    
    # 参数验证
    if tx_id in data["transactions"]:
        print(f"error: transaction '{tx_id}' already exists", file=sys.stderr)
        sys.exit(1)
    if account not in data["accounts"]:
        print(f"error: account '{account}' does not exist", file=sys.stderr)
        sys.exit(1)
    if category not in data["categories"]:
        print(f"error: category '{category}' does not exist", file=sys.stderr)
        sys.exit(1)
    if payment > 0 and deposit > 0:
        print("error: transaction cannot have both payment and deposit", file=sys.stderr)
        sys.exit(1)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        print("error: invalid date format, use YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)
    
    # 自动创建payee
    if payee not in data["payees"]:
        data["payees"][payee] = {"name": payee}
    
    # 创建交易
    data["transactions"][tx_id] = {
        "id": tx_id,
        "date": date,
        "account": account,
        "payee": payee,
        "notes": args.notes or "",
        "category": category}