import json
import random
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from config import DATA_DIR

SAMPLE_ACCOUNTS = [
    {"id": "acct_checking", "name": "Primary Checking", "type": "checking"},
    {"id": "acct_savings", "name": "High Yield Savings", "type": "savings"},
    {"id": "acct_credit_card", "name": "Sapphire Reserve Card", "type": "credit"},
]

SAMPLE_CATEGORIES = [
    {"id": "cat_groceries", "name": "Groceries"},
    {"id": "cat_dining", "name": "Restaurants & Coffee"},
    {"id": "cat_utilities", "name": "Utilities & Internet"},
    {"id": "cat_subscriptions", "name": "Subscriptions & Streaming"},
    {"id": "cat_gas", "name": "Gas & Fuel"},
    {"id": "cat_shopping", "name": "General Shopping"},
    {"id": "cat_income", "name": "Income / Payroll"},
    {"id": "cat_transfers", "name": "Transfers"},
]

SAMPLE_PAYEES = [
    {
        "id": "payee_trader_joes",
        "name": "Trader Joe's",
        "category_id": "cat_groceries",
        "raw_patterns": ["TRADER JOE'S #521 SAN FRANCISCO", "TRADER JOE'S #104 OAKLAND", "TRADER JOES CULVER CITY"],
        "amount_range": (-15000, -1500),
        "accounts": ["acct_checking", "acct_credit_card"]
    },
    {
        "id": "payee_whole_foods",
        "name": "Whole Foods",
        "category_id": "cat_groceries",
        "raw_patterns": ["WHOLEFD MKT #10294 SAN FRANCISCO", "WFM SOM 10492", "WHOLE FOODS MARKET"],
        "amount_range": (-22000, -2500),
        "accounts": ["acct_credit_card"]
    },
    {
        "id": "payee_starbucks",
        "name": "Starbucks",
        "category_id": "cat_dining",
        "raw_patterns": ["STARBUCKS STORE 08492", "STARBUCKS #19482 SF", "SQ *STARBUCKS COFFEE"],
        "amount_range": (-1200, -350),
        "accounts": ["acct_credit_card", "acct_checking"]
    },
    {
        "id": "payee_chipotle",
        "name": "Chipotle",
        "category_id": "cat_dining",
        "raw_patterns": ["CHIPOTLE 1849 SAN FRANCISCO CA", "CHIPOTLE ONLINE ORDER", "CHIPOTLE MEXICAN GRILL"],
        "amount_range": (-2800, -1100),
        "accounts": ["acct_credit_card"]
    },
    {
        "id": "payee_pg_e",
        "name": "PG&E",
        "category_id": "cat_utilities",
        "raw_patterns": ["PGAND-E UTILITY WEB PAY", "PGE SERVICE PAYMENT 8492", "PACIFIC GAS AND ELEC"],
        "amount_range": (-18000, -6000),
        "accounts": ["acct_checking"]
    },
    {
        "id": "payee_comcast",
        "name": "Xfinity / Comcast",
        "category_id": "cat_utilities",
        "raw_patterns": ["COMCAST CABLE COMM 84920", "XFINITY INTERNET AUTOPAY", "COMCAST INTERNET"],
        "amount_range": (-9000, -7000),
        "accounts": ["acct_checking"]
    },
    {
        "id": "payee_netflix",
        "name": "Netflix",
        "category_id": "cat_subscriptions",
        "raw_patterns": ["NETFLIX.COM DIG 800-542-492", "NETFLIX MOVIE SUBSCRIPTION", "NETFLIX US"],
        "amount_range": (-1549, -1549),
        "accounts": ["acct_credit_card"]
    },
    {
        "id": "payee_spotify",
        "name": "Spotify",
        "category_id": "cat_subscriptions",
        "raw_patterns": ["SPOTIFY USA 104928 SWEDEN", "SPOTIFY PREMIUM SUBSCRIPTION", "SPOTIFY USA"],
        "amount_range": (-1099, -1099),
        "accounts": ["acct_credit_card"]
    },
    {
        "id": "payee_chevron",
        "name": "Chevron",
        "category_id": "cat_gas",
        "raw_patterns": ["CHEVRON/GAS 009241 SAN JOSE", "CHEVRON 0941 OAKLAND CA", "CHEVRON OIL 9104"],
        "amount_range": (-6500, -2500),
        "accounts": ["acct_credit_card"]
    },
    {
        "id": "payee_amazon",
        "name": "Amazon",
        "category_id": "cat_shopping",
        "raw_patterns": ["AMZN Mktp US*2J9149A", "AMAZON.COM*8B9149A AMZN", "AMAZON RETAIL SEATTLE WA"],
        "amount_range": (-15000, -800),
        "accounts": ["acct_credit_card"]
    },
    {
        "id": "payee_employer",
        "name": "Acme Corp Payroll",
        "category_id": "cat_income",
        "raw_patterns": ["ACME CORP DIRECT DEP ACH", "ACME CORP PAYROLL DIR DEP", "ACME CORP SALARY"],
        "amount_range": (350000, 350000),
        "accounts": ["acct_checking"]
    }
]

def generate_synthetic_transactions(num_records: int = 1500, seed: int = 42) -> pd.DataFrame:
    """Generate realistic synthetic transaction history for training and validation."""
    random.seed(seed)
    start_date = datetime.now() - timedelta(days=365)
    records = []

    for i in range(num_records):
        tx_id = f"tx_{i+1:05d}"
        date_obj = start_date + timedelta(days=random.randint(0, 365))
        date_str = date_obj.strftime("%Y-%m-%d")

        # 10% chance of generating an internal transfer pair
        if random.random() < 0.10:
            transfer_cents = random.randint(10000, 150000)
            records.append({
                "id": f"tx_tr_a_{i}",
                "date": date_str,
                "amount": -transfer_cents,
                "account_id": "acct_checking",
                "imported_payee": f"ONLINE TRANSFER TO SAVINGS {random.randint(100,999)}",
                "payee_id": "payee_transfer_savings",
                "category_id": "cat_transfers",
                "is_transfer": True,
                "transfer_acct": "acct_savings",
                "transferred_id": f"tx_tr_b_{i}"
            })
            records.append({
                "id": f"tx_tr_b_{i}",
                "date": (date_obj + timedelta(days=random.randint(0, 2))).strftime("%Y-%m-%d"),
                "amount": transfer_cents,
                "account_id": "acct_savings",
                "imported_payee": f"ONLINE TRANSFER FROM CHECKING {random.randint(100,999)}",
                "payee_id": "payee_transfer_checking",
                "category_id": "cat_transfers",
                "is_transfer": True,
                "transfer_acct": "acct_checking",
                "transferred_id": f"tx_tr_a_{i}"
            })
            continue

        payee_spec = random.choice(SAMPLE_PAYEES)
        account_id = random.choice(payee_spec["accounts"])
        raw_pattern = random.choice(payee_spec["raw_patterns"])
        
        # Add random transaction noise (timestamps, numbers)
        if random.random() < 0.5:
            raw_payee = f"{raw_pattern} #{random.randint(1000,9999)}"
        else:
            raw_payee = raw_pattern

        min_amt, max_amt = payee_spec["amount_range"]
        amount = random.randint(min_amt, max_amt) if min_amt != max_amt else min_amt

        records.append({
            "id": tx_id,
            "date": date_str,
            "amount": amount,
            "account_id": account_id,
            "imported_payee": raw_payee,
            "payee_id": payee_spec["id"],
            "category_id": payee_spec["category_id"],
            "is_transfer": False,
            "transfer_acct": None,
            "transferred_id": None
        })

    df = pd.DataFrame(records)
    return df

def save_dataset(df: pd.DataFrame, filename: str = "dataset.json") -> Path:
    out_path = DATA_DIR / filename
    df.to_json(out_path, orient="records", indent=2)
    print(f"✓ Saved {len(df)} transactions to {out_path}")
    return out_path

def load_dataset(filename: str = "dataset.json") -> pd.DataFrame:
    in_path = DATA_DIR / filename
    if not in_path.exists():
        print(f"Dataset {in_path} not found. Generating synthetic dataset...")
        df = generate_synthetic_transactions()
        save_dataset(df, filename)
        return df
    return pd.read_json(in_path, orient="records")

if __name__ == "__main__":
    df = generate_synthetic_transactions(1500)
    save_dataset(df)
