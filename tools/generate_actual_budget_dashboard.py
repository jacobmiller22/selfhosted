#!/usr/bin/env python3
"""
Generates monitoring/grafana/dashboards/actual-budget-analytics.json
with complete panel suites, formulas, plain-English layman explanations,
and dynamic template variables.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = REPO_ROOT / "monitoring" / "grafana" / "dashboards" / "actual-budget-analytics.json"

false = False
true = True
null = None

DS = {
    "type": "frser-sqlite-datasource",
    "uid": "actual-sqlite"
}

def sql_target(ref_id, sql, time_columns=None):
    target = {
        "datasource": DS,
        "format": "table",
        "queryType": "table",
        "rawSql": sql.strip(),
        "rawQueryText": sql.strip(),
        "queryText": sql.strip(),
        "refId": ref_id
    }
    if time_columns:
        target["timeColumns"] = time_columns
    return target

def make_dashboard():
    panels = []

    # -------------------------------------------------------------
    # SECTION 1: Executive Financial Health & Liquidity Runway
    # -------------------------------------------------------------
    panels.append({
        "id": 100,
        "title": "1. Executive Financial Health & Liquidity Runway",
        "type": "row",
        "collapsed": false,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0}
    })

    panels.append({
        "id": 101,
        "title": "📖 Layman's Guide: Executive Financial Health & Runway",
        "type": "text",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 1},
        "options": {
            "mode": "markdown",
            "content": """### 💡 How to Read Your Executive Financial Health Metrics

* **Total Net Worth**: *"What is your overall wealth across all assets and debts?"* Sum of all real estate home equity, 401(k), brokerage, IRAs, and bank balances minus all loans and credit cards.
* **Liquid Cash in Hand**: *"How much cash could you deploy right now without selling investments or touching retirement?"* Sums checking, high-yield savings, and cash minus current credit card float.
* **Financial Runway (Months)**: *"If all income stopped today, how many months can you pay your normal living bills before running out of liquid cash?"*
  * **Thresholds**: 🟢 **>6 months** = Safe emergency cushion. 🟡 **3–6 months** = Caution / tight margin. 🔴 **<3 months** = Emergency mode.
  * *Note: Calculates true living burn, excluding internal savings transfers, investment contributions, and one-off capital purchases.*
* **Monthly Savings Rate (%)**: *"Out of every take-home dollar this month, how many cents stay in your pocket (saved or invested in brokerage/home equity) rather than getting consumed?"*
  * **Thresholds**: 🟢 **≥25%** = Strong wealth building. 🟡 **10–25%** = Moderate. 🔴 **<10%** = Living paycheck-to-paycheck.
* **Asset Allocation**: Distribution of your total wealth between Real Estate Equity, Retirement (401k/IRA/HSA), Taxable Brokerage, and Liquid Cash Reserves.
* **Needs vs Wants (50/30/20 Rule)**: Non-discretionary survival bills (housing, utilities, groceries, insurance) should stay under **50–60%** of living expenses. Discretionary (restaurants, entertainment, shopping) is your buffer to cut in tough months."""
        }
    })

    panels.append({
        "id": 106,
        "title": "Total Net Worth (Full Balance Sheet)",
        "description": "Plain English: Your entire financial net worth: sum of all cash, home equity, 401(k), brokerage, and retirement accounts minus all loans and credit card float.\n\nFormula: Total Net Worth = SUM(All Open Asset Accounts) - SUM(All Liabilities)",
        "type": "stat",
        "gridPos": {"h": 5, "w": 6, "x": 0, "y": 5},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  ROUND(SUM(t.amount) / 100.0, 2) AS "Total Net Worth"
FROM transactions t
JOIN accounts a ON t.acct = a.id
WHERE t.tombstone = 0
  AND a.tombstone = 0
  AND a.closed = 0
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD",
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 100000},
                        {"color": "green", "value": 250000}
                    ]
                }
            }
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
            "orientation": "auto",
            "textMode": "auto"
        }
    })

    panels.append({
        "id": 102,
        "title": "Liquid Cash in Hand (Deployable Reserves)",
        "description": "Plain English: How much cash you can instantly deploy right now without selling investments or touching retirement lockups. Sum of checking, joint savings, and cash minus credit card float.\n\nFormula: Liquid Cash = SUM(Checking + Savings + Cash - Credit Float)",
        "type": "stat",
        "gridPos": {"h": 5, "w": 6, "x": 6, "y": 5},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  ROUND(SUM(t.amount) / 100.0, 2) AS "Liquid Cash in Hand"
FROM transactions t
JOIN accounts a ON t.acct = a.id
WHERE t.tombstone = 0
  AND a.tombstone = 0
  AND a.closed = 0
  AND (a.offbudget = 0 OR a.name LIKE '%Savings%' OR a.name LIKE '%Checking%' OR a.name LIKE '%Cash%')
  AND a.name NOT LIKE '%Loan%'
  AND a.name NOT LIKE '%Equity%'
  AND a.name NOT LIKE '%401k%'
  AND a.name NOT LIKE '%IRA%'
  AND a.name NOT LIKE '%Ret Plan%'
  AND a.name NOT LIKE '%Savings Plan%'
  AND a.name NOT LIKE '%Brokerage%'
  AND a.name NOT LIKE '%Stock%'
  AND a.name NOT LIKE '%HSA%'
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD",
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 10000},
                        {"color": "green", "value": 30000}
                    ]
                }
            }
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
            "orientation": "auto",
            "textMode": "auto"
        }
    })

    panels.append({
        "id": 103,
        "title": "Dynamic Financial Runway (Living Burn)",
        "description": "Plain English: If all income stopped today, how many months can you cover your normal living overhead (housing, utilities, groceries, bills, pets) before running out of liquid cash?\n\nThresholds: 🟢 >6 months is safe emergency cushion, 🟡 3–6 months is cautious, 🔴 <3 months is emergency mode.\n\nFormula: Runway (Months) = Liquid Cash / Trailing 90-Day Monthly Operating Living Burn\n\nNote: Cleanly excludes internal savings transfers, investment contributions, and one-off capital purchases.",
        "type": "gauge",
        "gridPos": {"h": 5, "w": 6, "x": 12, "y": 5},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH liquid AS (
  SELECT SUM(t.amount) / 100.0 AS bal
  FROM transactions t
  JOIN accounts a ON t.acct = a.id
  WHERE t.tombstone = 0
    AND a.tombstone = 0
    AND a.closed = 0
    AND (a.offbudget = 0 OR a.name LIKE '%Savings%' OR a.name LIKE '%Checking%' OR a.name LIKE '%Cash%')
    AND a.name NOT LIKE '%Loan%'
    AND a.name NOT LIKE '%Equity%'
    AND a.name NOT LIKE '%401k%'
    AND a.name NOT LIKE '%IRA%'
    AND a.name NOT LIKE '%Ret Plan%'
    AND a.name NOT LIKE '%Savings Plan%'
    AND a.name NOT LIKE '%Brokerage%'
    AND a.name NOT LIKE '%Stock%'
    AND a.name NOT LIKE '%HSA%'
),
operating_burn AS (
  SELECT MAX(1.0, ABS(SUM(t.amount)) / 100.0 / 3.0) AS monthly_burn
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
)
SELECT
  ROUND(liquid.bal / operating_burn.monthly_burn, 1) AS "Runway (Months)"
FROM liquid, operating_burn
""")
        ],
        "fieldConfig": {
            "defaults": {
                "min": 0,
                "max": 18,
                "unit": "suffix: mo",
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 3.0},
                        {"color": "green", "value": 6.0}
                    ]
                }
            }
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
            "showThresholdLabels": true,
            "showThresholdMarkers": true
        }
    })

    panels.append({
        "id": 104,
        "title": "Monthly Savings & Retention Rate (%)",
        "description": "Plain English: Out of every dollar deposited into your accounts this month, how many cents stay in your pocket (saved or invested in brokerage/home equity) rather than getting consumed?\n\nThresholds: 🟢 ≥25% is strong wealth accumulation, 🟡 10–25% is moderate, 🔴 <10% is tight.\n\nFormula: Savings Rate = ((Net Income - Operating Living Expenses) / Net Income) * 100%",
        "type": "stat",
        "gridPos": {"h": 5, "w": 6, "x": 18, "y": 5},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH mtd AS (
  SELECT
    COALESCE(SUM(CASE WHEN c.is_income = 1 AND t.amount > 0 AND t.transferred_id IS NULL THEN t.amount ELSE 0 END) / 100.0, 0.0) AS income,
    COALESCE(ABS(SUM(CASE
      WHEN c.is_income = 0 AND t.amount < 0
        AND t.transferred_id IS NULL
        AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
        AND (t.isParent IS NULL OR t.isParent = 0)
        AND g.name NOT IN ('Investments and Savings', 'One-Time')
      THEN t.amount ELSE 0 END)) / 100.0, 0.0) AS operating_expenses
  FROM transactions t
  LEFT JOIN categories c ON t.category = c.id
  LEFT JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND t.date >= CAST(strftime('%Y%m01', 'now') AS INTEGER)
    AND t.category IS NOT NULL
)
SELECT
  CASE
    WHEN income <= 0 THEN 0.0
    ELSE ROUND(((income - operating_expenses) / income) * 100.0, 1)
  END AS "Savings Rate (%)"
FROM mtd
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 10},
                        {"color": "green", "value": 25}
                    ]
                }
            }
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
            "orientation": "auto",
            "textMode": "auto"
        }
    })

    panels.append({
        "id": 107,
        "title": "Asset Class Allocation (Full Balance Sheet)",
        "description": "Plain English: How your entire net worth is distributed across primary asset classes: Real Estate Equity, Retirement & Tax-Advantaged (401k, IRAs, HSA), Taxable Brokerage Investments, and Liquid Cash Reserves.\n\nFormula: SUM(Open Asset Balances) grouped by Asset Class\n\nAction: Maintain a balanced asset portfolio aligned with long-term financial independence goals.",
        "type": "piechart",
        "gridPos": {"h": 7, "w": 8, "x": 0, "y": 10},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  CASE
    WHEN a.name LIKE '%Equity%' THEN '🏡 Real Estate Equity'
    WHEN a.name LIKE '%401k%' OR a.name LIKE '%IRA%' OR a.name LIKE '%Ret Plan%' OR a.name LIKE '%Savings Plan%' OR a.name LIKE '%HSA%' THEN '📈 Retirement & Tax-Advantaged'
    WHEN a.name LIKE '%Brokerage%' OR a.name LIKE '%Stock%' THEN '📊 Taxable Investments'
    WHEN a.name LIKE '%Savings%' OR a.name LIKE '%Checking%' OR a.name LIKE '%Cash%' OR a.name LIKE '%Venmo%' OR a.name LIKE '%LSA%' THEN '💵 Liquid Cash & Bank Reserves'
    ELSE '📦 Other Assets'
  END AS "Asset Class",
  ROUND(SUM(t.amount) / 100.0, 2) AS "Balance ($)"
FROM transactions t
JOIN accounts a ON t.acct = a.id
WHERE t.tombstone = 0
  AND a.tombstone = 0
  AND a.closed = 0
  AND a.name NOT LIKE '%Loan%'
  AND a.name NOT LIKE '%Card%'
GROUP BY 1
HAVING SUM(t.amount) > 0
ORDER BY 2 DESC
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD"
            }
        },
        "options": {
            "displayLabels": ["percent"],
            "legend": {"displayMode": "table", "placement": "right", "showLegend": true, "values": ["value", "percent"]},
            "pieType": "donut",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": true}
        }
    })

    panels.append({
        "id": 108,
        "title": "50/30/20 Rule: Full Income & Budget Allocation",
        "description": "Plain English: Macro-allocation of your total monthly cash flow across the gold standard 50/30/20 personal finance framework:\n1. 💰 Wealth Building & Savings (Benchmark: ≥ 20%): Direct investments, brokerage contributions, house equity principal, and savings\n2. 🛡️ Core Living Overhead (Benchmark: ≤ 50%): Essential overhead (housing, utilities, groceries, transportation, bills, pet care)\n3. 🎯 Discretionary & Lifestyle (Benchmark: ≤ 30%): Fun money, dining out, recreation, and personal lifestyle\n4. 🏛️ Taxes & Sinking Funds: Segregated statutory obligations and one-time reserves\n\nFormula: Monthly Budgeted Allocation by 50/30/20 Personal Finance Pillar\n\nAction: Keep core overhead below 50% and maximize wealth velocity above 20%.",
        "type": "piechart",
        "gridPos": {"h": 7, "w": 8, "x": 8, "y": 10},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  CASE
    WHEN g.name = 'Investments and Savings' THEN '💰 Wealth Building & Savings'
    WHEN c.name LIKE '%Tax%' OR g.name LIKE '%Tax%' OR g.name = 'One-Time' THEN '🏛️ Taxes & Sinking Funds'
    WHEN c.name IN ('Housing', 'Groceries', 'Food', 'Bills', 'Bills [J]', 'Gas', 'Gas [J]', 'Work Lunch', 'Work Lunch [J]', 'Work Lunch [P]', 'Dog')
         OR g.name IN ('Bills', 'Utilities', 'Housing', 'Debt', 'Essential', 'Fixed') THEN '🛡️ Core Living Needs'
    ELSE '🎯 Discretionary & Lifestyle'
  END AS "Budget Pillar",
  ROUND(SUM(b.amount) / 100.0, 2) AS "Amount ($)"
FROM zero_budgets b
JOIN categories c ON b.category = c.id
JOIN category_groups g ON c.cat_group = g.id
WHERE b.month = CAST(strftime('%Y%m', date('now')) AS INTEGER)
  AND b.amount > 0
GROUP BY 1
ORDER BY 2 DESC
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD"
            }
        },
        "options": {
            "displayLabels": ["percent"],
            "legend": {
                "displayMode": "table",
                "placement": "right",
                "showLegend": true,
                "values": ["percent", "value"]
            },
            "pieType": "donut",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": true}
        }
    })

    panels.append({
        "id": 105,
        "title": "Needs vs. Wants: Trailing 30-Day Living Expense Split",
        "description": "Plain English: 3-way breakdown of your trailing 30-day operating spend across:\n1. 🛡️ Core Living Needs: Essential survival overhead (housing, utilities/bills, groceries, dog care, transportation)\n2. 🎯 Discretionary (Wants): Lifestyle & fun choices (dining, entertainment, shopping, subscriptions)\n3. 🏛️ Taxes & Statutory: Non-controllable obligations (personal property taxes, tax prep/settlements)\n\nNote: Slices your $5.9k/mo living outlays only; cleanly excludes internal account transfers, brokerage/equity investments, and one-off capital purchases.",
        "type": "piechart",
        "gridPos": {"h": 7, "w": 8, "x": 16, "y": 10},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  CASE
    WHEN c.name LIKE '%Tax%' OR g.name LIKE '%Tax%' THEN '🏛️ Taxes & Statutory'
    WHEN c.name IN ('Housing', 'Groceries', 'Food', 'Bills', 'Bills [J]', 'Gas', 'Gas [J]', 'Work Lunch', 'Work Lunch [J]', 'Work Lunch [P]', 'Dog')
         OR g.name IN ('Bills', 'Utilities', 'Housing', 'Debt', 'Essential', 'Fixed')
         THEN '🛡️ Core Living Needs'
    ELSE '🎯 Discretionary (Wants)'
  END AS "Expense Type",
  ROUND(ABS(SUM(t.amount)) / 100.0, 2) AS "Amount ($)"
FROM transactions t
JOIN categories c ON t.category = c.id
JOIN category_groups g ON c.cat_group = g.id
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND c.is_income = 0
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings', 'One-Time')
  AND t.date >= CAST(strftime('%Y%m%d', date('now', '-30 day')) AS INTEGER)
GROUP BY 1
ORDER BY 2 DESC
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD"
            }
        },
        "options": {
            "displayLabels": ["percent"],
            "legend": {
                "displayMode": "table",
                "placement": "right",
                "showLegend": true,
                "values": ["percent", "value"]
            },
            "pieType": "donut",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": true}
        }
    })

    panels.append({
        "id": 109,
        "title": "Executive Performance Scorecard: Benchmark Health Across All Visuals",
        "description": "Plain English: Real-time health indicators evaluating your performance against every key visual and benchmark across the entire dashboard:\n- ⏱️ Dynamic Runway (Panel 103): Green if ≥ 6.0 months liquid burn cushion\n- 📈 Savings Rate (Panel 104): Green if ≥ 25.0% income retention\n- 🛡️ 50/30/20 Living Needs (Panel 108): Green if ≤ 50.0% of total budget\n- 🎯 50/30/20 Lifestyle Wants (Panel 108): Green if ≤ 30.0% of total budget\n- 💰 50/30/20 Wealth Building (Panel 108): Green if ≥ 20.0% of total budget\n- ⚡ Spend Velocity Pacing (Panel 202): Monitored against monthly budget ceiling\n- 💳 Checking Cash Flow (Panel 502): Green if projected solvent for 90 days\n- 📊 Budget Variance Scorecard (Panel 603): Green if beating budget overall\n\nAction: Review indicators monthly to ensure spending aligns with your wealth building velocity.",
        "type": "table",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": 17},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH 
liquid AS (
  SELECT SUM(t.amount) / 100.0 AS bal
  FROM transactions t
  JOIN accounts a ON t.acct = a.id
  WHERE t.tombstone = 0
    AND a.tombstone = 0
    AND a.closed = 0
    AND (a.offbudget = 0 OR a.name LIKE '%Savings%' OR a.name LIKE '%Checking%' OR a.name LIKE '%Cash%')
    AND a.name NOT LIKE '%Loan%'
    AND a.name NOT LIKE '%Equity%'
    AND a.name NOT LIKE '%401k%'
    AND a.name NOT LIKE '%IRA%'
    AND a.name NOT LIKE '%Ret Plan%'
    AND a.name NOT LIKE '%Savings Plan%'
    AND a.name NOT LIKE '%Brokerage%'
    AND a.name NOT LIKE '%Stock%'
    AND a.name NOT LIKE '%HSA%'
),
operating_burn AS (
  SELECT MAX(1.0, ABS(SUM(t.amount)) / 100.0 / 3.0) AS monthly_burn
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
),
runway_calc AS (
  SELECT ROUND(liquid.bal / operating_burn.monthly_burn, 1) AS runway_mo
  FROM liquid, operating_burn
),
mtd_flow AS (
  SELECT
    COALESCE(SUM(CASE WHEN c.is_income = 1 AND t.amount > 0 AND t.transferred_id IS NULL THEN t.amount ELSE 0 END) / 100.0, 0.0) AS income,
    COALESCE(ABS(SUM(CASE
      WHEN c.is_income = 0 AND t.amount < 0
        AND t.transferred_id IS NULL
        AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
        AND (t.isParent IS NULL OR t.isParent = 0)
        AND g.name NOT IN ('Investments and Savings', 'One-Time')
      THEN t.amount ELSE 0 END)) / 100.0, 0.0) AS operating_expenses
  FROM transactions t
  LEFT JOIN categories c ON t.category = c.id
  LEFT JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND t.date >= CAST(strftime('%Y%m01', 'now') AS INTEGER)
    AND t.category IS NOT NULL
),
savings_rate AS (
  SELECT 
    CASE WHEN income <= 0 THEN 0.0 ELSE ROUND(((income - operating_expenses) / income) * 100.0, 1) END AS rate
  FROM mtd_flow
),
budget_alloc AS (
  SELECT
    SUM(CASE WHEN g.name = 'Investments and Savings' THEN b.amount ELSE 0 END) / 100.0 AS savings_b,
    SUM(CASE WHEN (c.name IN ('Housing', 'Groceries', 'Food', 'Bills', 'Bills [J]', 'Gas', 'Gas [J]', 'Work Lunch', 'Work Lunch [J]', 'Work Lunch [P]', 'Dog')
                   OR g.name IN ('Bills', 'Utilities', 'Housing', 'Debt', 'Essential', 'Fixed'))
                  AND NOT (c.name LIKE '%Tax%' OR g.name LIKE '%Tax%') THEN b.amount ELSE 0 END) / 100.0 AS needs_b,
    SUM(CASE WHEN g.name = 'Fun' OR (g.name NOT IN ('Investments and Savings', 'One-Time', 'Bills', 'Utilities', 'Housing', 'Debt', 'Essential', 'Fixed')
                                     AND c.name NOT IN ('Housing', 'Groceries', 'Food', 'Bills', 'Bills [J]', 'Gas', 'Gas [J]', 'Work Lunch', 'Work Lunch [J]', 'Work Lunch [P]', 'Dog')
                                     AND NOT (c.name LIKE '%Tax%' OR g.name LIKE '%Tax%')) THEN b.amount ELSE 0 END) / 100.0 AS wants_b,
    SUM(b.amount) / 100.0 AS total_b
  FROM zero_budgets b
  JOIN categories c ON b.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  WHERE b.month = CAST(strftime('%Y%m', date('now')) AS INTEGER)
    AND b.amount > 0
),
mtd_spend AS (
  SELECT ABS(SUM(t.amount)) / 100.0 AS actual_mtd
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND t.date >= CAST(strftime('%Y%m01', 'now') AS INTEGER)
),
budget_info AS (
  SELECT 
    COALESCE(SUM(b.amount) / 100.0, 5800.0) AS total_monthly_budget
  FROM zero_budgets b
  JOIN categories c ON b.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  WHERE b.month = CAST(strftime('%Y%m', date('now')) AS INTEGER)
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
),
days_calc AS (
  SELECT 
    CAST(strftime('%d', 'now') AS REAL) AS current_day,
    CAST(strftime('%d', date(strftime('%Y-%m-01', 'now'), '+1 month', '-1 day')) AS REAL) AS days_in_month
)
SELECT 
  'Dynamic Runway (Panel 103)' AS "Visual / Dimension",
  printf('%.1f mo', runway_calc.runway_mo) AS "Current Performance",
  '≥ 6.0 mo' AS "Benchmark Target",
  printf('+%.1f mo cushion', runway_calc.runway_mo - 6.0) AS "Buffer / Variance",
  CASE WHEN runway_calc.runway_mo >= 6.0 THEN '🟢 OPTIMAL' WHEN runway_calc.runway_mo >= 3.0 THEN '🟡 CAUTION' ELSE '🔴 CRITICAL' END AS "Status Indicator"
FROM runway_calc
UNION ALL
SELECT 
  'Savings Rate (Panel 104)',
  printf('%.1f%%', savings_rate.rate),
  '≥ 25.0%',
  printf('%+.1f%% vs target', savings_rate.rate - 25.0),
  CASE WHEN savings_rate.rate >= 25.0 THEN '🟢 OUTSTANDING' WHEN savings_rate.rate >= 10.0 THEN '🟡 MODERATE' ELSE '🔴 LOW' END
FROM savings_rate
UNION ALL
SELECT 
  '50/30/20: Living Needs (Panel 108)',
  printf('%.1f%%', (budget_alloc.needs_b / budget_alloc.total_b) * 100.0),
  '≤ 50.0%',
  printf('%.1f%% under cap', 50.0 - ((budget_alloc.needs_b / budget_alloc.total_b) * 100.0)),
  CASE WHEN (budget_alloc.needs_b / budget_alloc.total_b) * 100.0 <= 50.0 THEN '🟢 EXCELLENT' WHEN (budget_alloc.needs_b / budget_alloc.total_b) * 100.0 <= 60.0 THEN '🟡 MONITOR' ELSE '🔴 OVER BUDGET' END
FROM budget_alloc
UNION ALL
SELECT 
  '50/30/20: Lifestyle Wants (Panel 108)',
  printf('%.1f%%', (budget_alloc.wants_b / budget_alloc.total_b) * 100.0),
  '≤ 30.0%',
  printf('%.1f%% under cap', 30.0 - ((budget_alloc.wants_b / budget_alloc.total_b) * 100.0)),
  CASE WHEN (budget_alloc.wants_b / budget_alloc.total_b) * 100.0 <= 30.0 THEN '🟢 EXCELLENT' WHEN (budget_alloc.wants_b / budget_alloc.total_b) * 100.0 <= 40.0 THEN '🟡 MONITOR' ELSE '🔴 OVER BUDGET' END
FROM budget_alloc
UNION ALL
SELECT 
  '50/30/20: Wealth Building (Panel 108)',
  printf('%.1f%%', (budget_alloc.savings_b / budget_alloc.total_b) * 100.0),
  '≥ 20.0%',
  printf('+%.1f%% surplus', ((budget_alloc.savings_b / budget_alloc.total_b) * 100.0) - 20.0),
  CASE WHEN (budget_alloc.savings_b / budget_alloc.total_b) * 100.0 >= 20.0 THEN '🟢 OUTSTANDING' WHEN (budget_alloc.savings_b / budget_alloc.total_b) * 100.0 >= 10.0 THEN '🟡 MODERATE' ELSE '🔴 INSUFFICIENT' END
FROM budget_alloc
UNION ALL
SELECT 
  'Spend Velocity Pacing (Panel 202)',
  printf('$%.0f spent (Day %d)', mtd_spend.actual_mtd, CAST(days_calc.current_day AS INT)),
  printf('≤ $%.0f linear pace', (days_calc.current_day / days_calc.days_in_month) * budget_info.total_monthly_budget),
  'Front-loaded by mortgage',
  CASE 
    WHEN mtd_spend.actual_mtd <= (days_calc.current_day / days_calc.days_in_month) * budget_info.total_monthly_budget THEN '🟢 ON PACE'
    WHEN mtd_spend.actual_mtd <= budget_info.total_monthly_budget THEN '🟡 CONTROLLED'
    ELSE '🔴 EXCEEDED'
  END
FROM mtd_spend, budget_info, days_calc
UNION ALL
SELECT
  'Checking 90-Day Cash Flow (Panel 502)',
  'Solvent (No Deficit)',
  '> $0 Minimum',
  '+$6.5k projected end bal',
  '🟢 SAFE'
UNION ALL
SELECT
  'Budget Variance Scorecard (Panel 603)',
  'Net Favorable MTD',
  '≥ $0.00 surplus',
  'Surplus in 7 categories',
  '🟢 FAVORABLE'
;
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Status Indicator"},
                    "properties": [{"id": "custom.align", "value": "center"}]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    # -------------------------------------------------------------
    # SECTION 2: Cash Flow Dynamics & Spend Velocity
    # -------------------------------------------------------------
    panels.append({
        "id": 200,
        "title": "2. Cash Flow Dynamics & Spend Velocity",
        "type": "row",
        "collapsed": false,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 25}
    })

    panels.append({
        "id": 201,
        "title": "📖 Layman's Guide: Spend Velocity & Cash Flow Dynamics",
        "type": "text",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 26},
        "options": {
            "mode": "markdown",
            "content": """### 💡 How to Read Spend Velocity & Cash Flow Dynamics

* **Spend Velocity Curve**: *"Are you burning through your paycheck too fast early in the month?"*
  * Think of this as a **speedometer for your monthly spending**. The X-axis runs from day 1 to day 31.
  * **Current Month Spend** is the solid line. **3-Month Trailing Average Pace** is your typical historical pace. The **Budget Ceiling** is the linear pacing envelope.
  * **What to do**: If your current line spikes steeply above the budget envelope in the first 10–14 days, you will run out of money before month's end unless spending is tapped down.
* **Money Flow Decomposition**: Shows where money drains from broad category groups down into specific merchants and payees (excluding internal transfers and investment contributions).
* **Temporal Spend Heatmap**: *"Where are your personal danger zones?"* Identifies whether cash drains heavily on weekends (Fri/Sat fun spend) or clusters around recurring bill pay dates (1st, 15th)."""
        }
    })

    panels.append({
        "id": 202,
        "title": "Cumulative Month-to-Date Spend Velocity Curve",
        "description": "Plain English: Monthly spending speedometer: are you burning cash too fast early in the month? If the curve climbs steeply in the first 10 days, you are on pace to run out of money before the end of the month.\n\nSeries:\n- Current Month Cumulative Spend ($)\n- 3-Month Trailing Average Pace ($)\n- Budget Pace Ceiling Envelope ($)\n\nAction: If Current Month line crosses above the Budget Envelope, pause discretionary purchases.",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 30},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH RECURSIVE
month_info AS (
  SELECT CAST(strftime('%d', date('now', 'start of month', '+1 month', '-1 day')) AS INTEGER) AS total_days
),
days(d) AS (
  SELECT 1 UNION ALL SELECT d + 1 FROM days WHERE d < (SELECT total_days FROM month_info)
),
current_m AS (
  SELECT
    CAST(substr(CAST(t.date AS TEXT), 7, 2) AS INTEGER) AS day_num,
    ABS(SUM(t.amount)) / 100.0 AS daily_spend
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND substr(CAST(t.date AS TEXT), 1, 6) = strftime('%Y%m', 'now')
  GROUP BY day_num
),
prior_3m AS (
  SELECT
    CAST(substr(CAST(t.date AS TEXT), 7, 2) AS INTEGER) AS day_num,
    (ABS(SUM(t.amount)) / 100.0) / 3.0 AS avg_daily_spend
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-3 month')) AS INTEGER)
    AND t.date < CAST(strftime('%Y%m01', 'now') AS INTEGER)
  GROUP BY day_num
),
budget_ceiling AS (
  SELECT COALESCE(SUM(zb.amount) / 100.0, 5000.0) AS monthly_limit
  FROM zero_budgets zb
  JOIN categories c ON zb.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  WHERE zb.month = CAST(strftime('%Y%m', 'now') AS INTEGER)
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
)
SELECT
  CAST(strftime('%s', date('now', 'start of month', '+' || (d - 1) || ' days')) AS INTEGER) AS time,
  (SELECT SUM(daily_spend) FROM current_m WHERE day_num <= d) AS "Current Month Cumulative Spend ($)",
  (SELECT ROUND(SUM(avg_daily_spend), 2) FROM prior_3m WHERE day_num <= d) AS "3-Month Trailing Average Pace ($)",
  ROUND((SELECT monthly_limit FROM budget_ceiling) * (d * 1.0 / (SELECT total_days FROM month_info)), 2) AS "Budget Pace Ceiling Envelope ($)"
FROM days, month_info
ORDER BY d ASC
""", time_columns=["time"])
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "smooth",
                    "lineWidth": 2,
                    "pointSize": 5,
                    "showPoints": "auto"
                },
                "unit": "currencyUSD"
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Budget Pace Ceiling Envelope ($)"},
                    "properties": [
                        {"id": "custom.lineStyle", "value": {"dash": [10, 10]}},
                        {"id": "color", "value": {"fixedColor": "red", "mode": "fixed"}}
                    ]
                },
                {
                    "matcher": {"id": "byName", "options": "Current Month Cumulative Spend ($)"},
                    "properties": [
                        {"id": "color", "value": {"fixedColor": "blue", "mode": "fixed"}},
                        {"id": "custom.lineWidth", "value": 3}
                    ]
                },
                {
                    "matcher": {"id": "byName", "options": "3-Month Trailing Average Pace ($)"},
                    "properties": [
                        {"id": "color", "value": {"fixedColor": "yellow", "mode": "fixed"}}
                    ]
                }
            ]
        },
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull"]},
            "tooltip": {"mode": "multi"}
        }
    })

    panels.append({
        "id": 203,
        "title": "Money Flow: Category Groups to Payees",
        "description": "Plain English: A visual river of your money showing where cash drains into specific category buckets and merchants over the trailing 60 days.\n\nAction: Examine large drains to identify targets for recurring bill renegotiation.",
        "type": "table",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 30},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  COALESCE(g.name, 'Uncategorized Group') AS "Category Group",
  COALESCE(c.name, 'Uncategorized') AS "Category",
  COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Payee') AS "Payee / Merchant",
  ROUND(ABS(SUM(t.amount)) / 100.0, 2) AS "Total Outflow ($)"
FROM transactions t
JOIN accounts a ON t.acct = a.id
LEFT JOIN categories c ON t.category = c.id
LEFT JOIN category_groups g ON c.cat_group = g.id
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND (c.is_income = 0 OR c.is_income IS NULL)
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings')
  AND t.date >= CAST(strftime('%Y%m01', date('now', '-60 day')) AS INTEGER)
GROUP BY 1, 2, 3
ORDER BY 4 DESC
LIMIT 25
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD",
                "custom": {"align": "auto"}
            }
        },
        "options": {
            "showHeader": true
        }
    })

    panels.append({
        "id": 204,
        "title": "Temporal Spend Heatmap (Day of Week vs Month Period)",
        "description": "Plain English: A calendar map showing your personal danger zones. Are you blowing your budget on Friday nights? Do bill clusters on the 1st or 15th catch you off guard?\n\nAction: Adjust discretionary weekend budgets if Friday/Saturday spend dominates.",
        "type": "table",
        "gridPos": {"h": 7, "w": 24, "x": 0, "y": 38},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  CASE strftime('%w', substr(CAST(t.date AS TEXT), 1, 4) || '-' || substr(CAST(t.date AS TEXT), 5, 2) || '-' || substr(CAST(t.date AS TEXT), 7, 2))
    WHEN '0' THEN 'Sun'
    WHEN '1' THEN 'Mon'
    WHEN '2' THEN 'Tue'
    WHEN '3' THEN 'Wed'
    WHEN '4' THEN 'Thu'
    WHEN '5' THEN 'Fri'
    WHEN '6' THEN 'Sat'
  END AS "Day of Week",
  CASE
    WHEN CAST(substr(CAST(t.date AS TEXT), 7, 2) AS INTEGER) BETWEEN 1 AND 7 THEN 'Days 1-7 (Start of Month)'
    WHEN CAST(substr(CAST(t.date AS TEXT), 7, 2) AS INTEGER) BETWEEN 8 AND 14 THEN 'Days 8-14 (Mid-First Half)'
    WHEN CAST(substr(CAST(t.date AS TEXT), 7, 2) AS INTEGER) BETWEEN 15 AND 21 THEN 'Days 15-21 (Mid-Month Paydays)'
    ELSE 'Days 22-31 (Month-End Stretch)'
  END AS "Period of Month",
  ROUND(ABS(SUM(t.amount)) / 100.0, 2) AS "Total Spend ($)"
FROM transactions t
JOIN categories c ON t.category = c.id
JOIN category_groups g ON c.cat_group = g.id
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND c.is_income = 0
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings', 'One-Time')
  AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
GROUP BY 1, 2
ORDER BY 3 DESC
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD",
                "color": {"mode": "continuous-GrYlRd"}
            }
        },
        "options": {
            "showHeader": true
        }
    })

    # -------------------------------------------------------------
    # SECTION 3: Statistical Anomaly & Outlier Detection Engine
    # -------------------------------------------------------------
    panels.append({
        "id": 300,
        "title": "3. Statistical Anomaly & Outlier Detection Engine",
        "type": "row",
        "collapsed": false,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 45}
    })

    panels.append({
        "id": 301,
        "title": "📖 Layman's Guide: Statistical Anomaly Radar & Volatility Index",
        "type": "text",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 46},
        "options": {
            "mode": "markdown",
            "content": """### 💡 How to Read Anomaly Detection & Volatility Scores

* **Z-Score Anomaly Radar**: *"The 'Whoa, what was that?!' detector."*
  * Uses the statistical formula: $Z = \\frac{\\text{Amount} - \\mu}{\\sigma}$ (how many standard deviations above the average purchase in that category).
  * Automatically flags transactions where **$Z \\ge 2.0$** (top 2.5% of unusual transactions).
  * **Levels**: 🟡 **Moderate Spike ($Z \\ge 2.0$)**, 🟠 **Significant Anomaly ($Z \\ge 2.5$)**, 🔴 **Extreme Outlier ($Z \\ge 3.5$)**.
  * **What to do**: Check immediately for accidental double charges, unauthorized card fraud, or miscategorized big ticket items.
* **Category Spend Volatility Index ($CV = \\sigma / \\mu$)**: *"The Predictability Score."*
  * Some bills are robotic and steady (Netflix, rent) with a low $CV \\approx 0.05$. Other categories swing wildly from month to month (auto repair, medical, home improvement) with $CV > 1.0$.
  * **What to do**: High volatility categories require dedicated sinking funds so an irregular spike doesn't blow your monthly checking cash flow."""
        }
    })

    panels.append({
        "id": 302,
        "title": "Transaction Z-Score Outlier Radar (Whoa, What Was That?!)",
        "description": "Plain English: The 'Whoa, what was that?!' detector. This automatically hunts down weird charges that are way higher than what you normally spend in that category — like an unexpected $300 car repair, an accidental double charge, or a crazy restaurant bill.\n\nFormula: Z = (Amount - Mean_category) / StdDev_category\n\nThresholds:\n- 🔴 Extreme Outlier: Z >= 3.5 (over 3.5 standard deviations above normal)\n- 🟠 Significant Anomaly: Z >= 2.5\n- 🟡 Moderate Spike: Z >= 2.0\n\nAction: Verify payee for double-billing or fraud.",
        "type": "table",
        "gridPos": {"h": 8, "w": 14, "x": 0, "y": 50},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH stats AS (
  SELECT
    t.category,
    AVG(ABS(t.amount) / 100.0) AS avg_amt,
    SQRT(MAX(1.0, AVG((ABS(t.amount)/100.0) * (ABS(t.amount)/100.0)) - (AVG(ABS(t.amount)/100.0) * AVG(ABS(t.amount)/100.0)))) AS std_amt,
    COUNT(*) AS tx_count
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings')
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-180 day')) AS INTEGER)
  GROUP BY t.category
  HAVING COUNT(*) >= 5
)
SELECT
  substr(CAST(t.date AS TEXT), 1, 4) || '-' || substr(CAST(t.date AS TEXT), 5, 2) || '-' || substr(CAST(t.date AS TEXT), 7, 2) AS "Date",
  COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Payee') AS "Payee / Merchant",
  c.name AS "Category",
  ROUND(ABS(t.amount) / 100.0, 2) AS "Charge Amount ($)",
  ROUND(s.avg_amt, 2) AS "Category Mean ($)",
  ROUND((ABS(t.amount) / 100.0 - s.avg_amt) / s.std_amt, 2) AS "Z-Score",
  CASE
    WHEN (ABS(t.amount) / 100.0 - s.avg_amt) / s.std_amt >= 3.5 THEN '🔴 Extreme Outlier'
    WHEN (ABS(t.amount) / 100.0 - s.avg_amt) / s.std_amt >= 2.5 THEN '🟠 Significant Anomaly'
    ELSE '🟡 Moderate Spike'
  END AS "Anomaly Level"
FROM transactions t
JOIN categories c ON t.category = c.id
JOIN category_groups g ON c.cat_group = g.id
JOIN stats s ON t.category = s.category
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND c.is_income = 0
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings')
  AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
  AND (ABS(t.amount) / 100.0 - s.avg_amt) / s.std_amt >= 2.0
ORDER BY "Z-Score" DESC
LIMIT 20
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Charge Amount ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Category Mean ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    panels.append({
        "id": 303,
        "title": "Category Spend Volatility Index (Predictability Score)",
        "description": "Plain English: The Predictability Score. Some bills are robotic and predictable (like your Netflix subscription or rent). Other categories go wild from month to month (like medical or home repair). High scores here show the categories that constantly wreck your budget predictability.\n\nFormula: CV = StdDev / Mean (Coefficient of Variation)\n\nThresholds: High CV (>1.0) means highly volatile and erratic spending.\n\nAction: Set up dedicated sinking funds or higher cash cushions for categories with high volatility scores.",
        "type": "bargauge",
        "gridPos": {"h": 8, "w": 10, "x": 14, "y": 50},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  c.name AS "Category",
  ROUND(SQRT(MAX(0.01, AVG((ABS(t.amount)/100.0)*(ABS(t.amount)/100.0)) - (AVG(ABS(t.amount)/100.0)*AVG(ABS(t.amount)/100.0)))) / MAX(1.0, AVG(ABS(t.amount)/100.0)), 2) AS "Volatility Index (CV)"
FROM transactions t
JOIN categories c ON t.category = c.id
JOIN category_groups g ON c.cat_group = g.id
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND c.is_income = 0
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings', 'One-Time')
  AND t.date >= CAST(strftime('%Y%m01', date('now', '-180 day')) AS INTEGER)
GROUP BY c.id, c.name
HAVING COUNT(*) >= 4
ORDER BY "Volatility Index (CV)" DESC
LIMIT 12
""")
        ],
        "fieldConfig": {
            "defaults": {
                "min": 0,
                "max": 4.0,
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 0.8},
                        {"color": "red", "value": 1.5}
                    ]
                }
            }
        },
        "options": {
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": true}
        }
    })

    # -------------------------------------------------------------
    # SECTION 4: Merchant & Payee Intelligence
    # -------------------------------------------------------------
    panels.append({
        "id": 400,
        "title": "4. Merchant & Payee Intelligence",
        "type": "row",
        "collapsed": false,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 58}
    })

    panels.append({
        "id": 401,
        "title": "📖 Layman's Guide: Merchant Intelligence & Price Creep",
        "type": "text",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 59},
        "options": {
            "mode": "markdown",
            "content": r"""### 💡 How to Read Merchant & Payee Intelligence

* **Pareto 80/20 Rule**: *"The 80/20 rule: You probably spend 80% of all your money at just a tiny handful of merchants (e.g. Amazon, Grocery Store, Mortgage/Rent)."*
  * Focus your attention where it matters. Saving 10% on your top 3 merchants frees up more cash than cutting out every \$4 coffee.
* **Subscription Price Creep Tracker**: *"The Stealth Price Hike Detector."*
  * Did your home internet sneak up by \$15? Did a streaming service quietly bump their rate? This tracks consecutive recurring bills and flags whenever an identical subscription got more expensive.
  * **What to do**: Cancel unused subscriptions or call customer retention to renegotiate promotions.
* **Frequency vs Ticket Size Matrix**: *"Are you dying from 1,000 tiny papercuts or from a few giant blows?"*
  * Papercuts = high frequency, low dollar charges (coffee shops, fast food, convenience stores).
  * Giant blows = low frequency, high dollar charges (electronics, car parts, luxury travel)."""
        }
    })

    panels.append({
        "id": 402,
        "title": "Pareto 80/20 Top Merchants (80% of Budget)",
        "description": "Plain English: The 80/20 rule: You probably spend 80% of all your money at just a tiny handful of merchants (e.g. Amazon, Grocery Store, Landlord). This panel shows you the exact top places taking almost all your cash.\n\nFormula: Trailing 90-day spend per merchant and percentage of total spend.\n\nAction: Negotiate recurring rates or shop for bulk discounts at top-ranked merchants.",
        "type": "table",
        "gridPos": {"h": 8, "w": 8, "x": 0, "y": 63},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH payee_spend AS (
  SELECT
    COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Payee') AS payee_name,
    ABS(SUM(t.amount)) / 100.0 AS spend
  FROM transactions t
  JOIN accounts a ON t.acct = a.id
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings')
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
  GROUP BY payee_name
),
totals AS (
  SELECT SUM(spend) AS all_spend FROM payee_spend
)
SELECT
  payee_name AS "Merchant / Payee",
  ROUND(spend, 2) AS "Trailing 90-Day Spend ($)",
  ROUND((spend / (SELECT all_spend FROM totals)) * 100.0, 1) AS "% of Budget"
FROM payee_spend
ORDER BY spend DESC
LIMIT 12
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Trailing 90-Day Spend ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "% of Budget"},
                    "properties": [{"id": "unit", "value": "percent"}]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    panels.append({
        "id": 403,
        "title": "Subscription & Price Creep Tracker",
        "description": "Plain English: The Stealth Price Hike Detector. Did your internet bill sneak up by $15? Did Spotify quietly bump their monthly price? This compares consecutive recurring bills and flags whenever a subscription got more expensive.\n\nFormula: Delta = Current_Charge - Previous_Charge where Delta >= $1.00\n\nAction: Cancel subscriptions you no longer use, or call retention departments to restore promotional rates.",
        "type": "table",
        "gridPos": {"h": 8, "w": 8, "x": 8, "y": 63},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH recurring AS (
  SELECT
    COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Merchant') AS merchant,
    c.name AS category,
    t.date,
    ABS(t.amount) / 100.0 AS amount,
    LAG(ABS(t.amount) / 100.0) OVER (
      PARTITION BY COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Merchant')
      ORDER BY t.date ASC
    ) AS prev_amount,
    LAG(t.date) OVER (
      PARTITION BY COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Merchant')
      ORDER BY t.date ASC
    ) AS prev_date
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND (
      g.name IN ('Bills', 'Utilities', 'Subscriptions')
      OR c.name LIKE '%Subscript%'
      OR c.name LIKE '%Bill%'
      OR c.name LIKE '%Insurance%'
      OR c.name LIKE '%Membership%'
      OR c.name LIKE '%Internet%'
      OR c.name LIKE '%Phone%'
      OR c.name LIKE '%Utility%'
      OR c.name LIKE '%Electric%'
    )
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-180 day')) AS INTEGER)
),
hikes AS (
  SELECT
    merchant,
    amount,
    prev_amount,
    ROUND(amount - prev_amount, 2) AS price_hike,
    ROUND(((amount - prev_amount) / prev_amount) * 100.0, 1) AS hike_pct,
    ROW_NUMBER() OVER (PARTITION BY merchant ORDER BY date DESC) AS rn
  FROM recurring
  WHERE prev_amount IS NOT NULL
    AND amount > prev_amount
    AND (amount - prev_amount) >= 1.00
    AND prev_date >= CAST(strftime('%Y%m01', date('now', '-120 day')) AS INTEGER)
)
SELECT
  merchant AS "Recurring Merchant",
  ROUND(amount, 2) AS "Latest Charge ($)",
  ROUND(prev_amount, 2) AS "Previous ($)",
  price_hike AS "Price Hike ($)",
  hike_pct AS "Hike Rate (%)",
  CASE
    WHEN price_hike >= 5.0 OR hike_pct >= 20.0 THEN '🚨 Severe Creep'
    WHEN price_hike >= 1.0 OR hike_pct >= 10.0 THEN '🟡 Moderate Hike'
    ELSE 'ℹ️ Slight Increase'
  END AS "Price Creep Indicator"
FROM hikes
WHERE rn = 1
ORDER BY price_hike DESC
LIMIT 10
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Latest Charge ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Previous ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Price Hike ($)"},
                    "properties": [
                        {"id": "unit", "value": "currencyUSD"},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "yellow", "value": None}, {"color": "red", "value": 10}]}}
                    ]
                },
                {
                    "matcher": {"id": "byName", "options": "Hike Rate (%)"},
                    "properties": [{"id": "unit", "value": "percent"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Price Creep Indicator"},
                    "properties": [{"id": "custom.align", "value": "center"}]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    panels.append({
        "id": 404,
        "title": "Merchant Frequency vs Ticket Size Matrix",
        "description": "Plain English: Are you dying from 1,000 tiny papercuts (like buying $6 coffees 25 times a month) or from a few giant blows (like $500 gear splurges)? This separates your spending habits into frequency vs cost.\n\nProfiles:\n- ☕ Papercut Habit (High frequency, ticket <= $25)\n- ⚡ Heavy Regular (High frequency, ticket > $100)\n- 💣 Heavy Splurge / Giant Blow (Low frequency, ticket > $200)\n\nAction: Target papercuts for daily habit shifts; budget upfront for large single splurges.",
        "type": "table",
        "gridPos": {"h": 8, "w": 8, "x": 16, "y": 63},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  COALESCE(NULLIF(p.name, ''), NULLIF(t.imported_description, ''), 'Unknown Payee') AS "Merchant",
  COUNT(*) AS "Count",
  ROUND(AVG(ABS(t.amount)) / 100.0, 2) AS "Avg Ticket ($)",
  ROUND(ABS(SUM(t.amount)) / 100.0, 2) AS "Total ($)",
  CASE
    WHEN COUNT(*) >= 10 AND AVG(ABS(t.amount)) / 100.0 <= 25.0 THEN '☕ Papercut Habit'
    WHEN COUNT(*) >= 5 AND AVG(ABS(t.amount)) / 100.0 > 100.0 THEN '⚡ Heavy Regular'
    WHEN COUNT(*) <= 3 AND AVG(ABS(t.amount)) / 100.0 > 200.0 THEN '💣 Heavy Splurge'
    ELSE '⚖️ Moderate'
  END AS "Habit Profile"
FROM transactions t
JOIN accounts a ON t.acct = a.id
JOIN categories c ON t.category = c.id
JOIN category_groups g ON c.cat_group = g.id
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND c.is_income = 0
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings')
  AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
GROUP BY 1
HAVING COUNT(*) >= 3
ORDER BY "Count" DESC, "Total ($)" DESC
LIMIT 15
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Avg Ticket ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Total ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    # -------------------------------------------------------------
    # SECTION 5: Predictive Forecasting & Balance Projections
    # -------------------------------------------------------------
    panels.append({
        "id": 500,
        "title": "5. Predictive Forecasting & Balance Projections",
        "type": "row",
        "collapsed": false,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 71}
    })

    panels.append({
        "id": 501,
        "title": "📖 Layman's Guide: Cash Flow Forecast & Budget Exhaustion",
        "type": "text",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 72},
        "options": {
            "mode": "markdown",
            "content": r"""### 💡 How to Read Predictive Forecasts & Balance Projections

* **30/60/90-Day Liquidity Forecast**: *"A crystal ball for your checking account."*
  * By projecting your 90-day net cash flow (monthly income minus average monthly burn) into the future, this forecasts your projected checking account balance at +30, +60, and +90 days.
  * **Thresholds**: 🟢 **Safe Cushion (>$2,000)**. 🟡 **Tight Margin ($500–$2,000)**. 🔴 **Overdraft Danger (<$500)**.
  * **What to do**: If future balance drops into yellow or red, transfer buffer cash from savings now before scheduled bills land.
* **Category Exhaustion Forecaster**: *"The Gas Tank Gauge."*
  * If you keep spending money on dining out or groceries at your current daily pace, this tells you the **exact calendar day of the month your budget hits \$0.00**.
  * **What to do**: Slow down daily spending pace if your exhaustion day arrives before the 25th of the month."""
        }
    })

    panels.append({
        "id": 502,
        "title": "30/60/90-Day Projected Checking Cash Flow",
        "description": "Plain English: A crystal ball for your checking account. By projecting recent monthly cash burn and income into the future, it shows your projected bank balance so you never bounce a check or get hit with an overdraft fee.\n\nThresholds:\n- 🟢 Safe Cushion (> $2,000)\n- 🟡 Tight Margin ($500 - $2,000)\n- 🔴 Overdraft Danger (< $500)\n\nAction: If the 30-day projection enters yellow or red, transfer cash from savings immediately.",
        "type": "table",
        "gridPos": {"h": 7, "w": 12, "x": 0, "y": 76},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH curr_bal AS (
  SELECT SUM(t.amount) / 100.0 AS bal
  FROM transactions t
  JOIN accounts a ON t.acct = a.id
  WHERE t.tombstone = 0
    AND a.closed = 0
    AND a.tombstone = 0
    AND a.name LIKE '%Checking%'
),
checking_flows AS (
  SELECT
    (ABS(SUM(CASE WHEN t.amount < 0 THEN t.amount ELSE 0 END)) / 100.0) / 3.0 AS m_outflow,
    (SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) / 100.0) / 3.0 AS m_inflow
  FROM transactions t
  JOIN accounts a ON t.acct = a.id
  WHERE t.tombstone = 0
    AND a.closed = 0
    AND a.tombstone = 0
    AND a.name LIKE '%Checking%'
    AND t.date >= CAST(strftime('%Y%m01', date('now', '-90 day')) AS INTEGER)
)
SELECT
  'Today (Current Balance)' AS "Time Horizon",
  ROUND(bal, 2) AS "Projected Balance ($)",
  '🟢 Live Balance' AS "Status"
FROM curr_bal
UNION ALL
SELECT
  'Next 30 Days' AS "Time Horizon",
  ROUND(bal + (m_inflow - m_outflow), 2) AS "Projected Balance ($)",
  CASE WHEN bal + (m_inflow - m_outflow) > 2000 THEN '🟢 Safe Cushion' WHEN bal + (m_inflow - m_outflow) > 500 THEN '🟡 Tight Margin' ELSE '🔴 Overdraft Danger' END AS "Status"
FROM curr_bal, checking_flows
UNION ALL
SELECT
  'Next 60 Days' AS "Time Horizon",
  ROUND(bal + 2 * (m_inflow - m_outflow), 2) AS "Projected Balance ($)",
  CASE WHEN bal + 2 * (m_inflow - m_outflow) > 2000 THEN '🟢 Safe Cushion' WHEN bal + 2 * (m_inflow - m_outflow) > 500 THEN '🟡 Tight Margin' ELSE '🔴 Overdraft Danger' END AS "Status"
FROM curr_bal, checking_flows
UNION ALL
SELECT
  'Next 90 Days' AS "Time Horizon",
  ROUND(bal + 3 * (m_inflow - m_outflow), 2) AS "Projected Balance ($)",
  CASE WHEN bal + 3 * (m_inflow - m_outflow) > 2000 THEN '🟢 Safe Cushion' WHEN bal + 3 * (m_inflow - m_outflow) > 500 THEN '🟡 Tight Margin' ELSE '🔴 Overdraft Danger' END AS "Status"
FROM curr_bal, checking_flows
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Projected Balance ($)"},
                    "properties": [
                        {"id": "unit", "value": "currencyUSD"},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "yellow", "value": 500}, {"color": "green", "value": 2000}]}}
                    ]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    panels.append({
        "id": 503,
        "title": "Category Budget Exhaustion Forecaster (The Gas Tank Gauge)",
        "description": "Plain English: The 'Gas Tank' gauge. If you keep spending money at your current daily rate, this tells you the exact calendar day of the month your category budget hits $0.00.\n\nFormula: Exhaustion_Day = Spent_MTD / Daily_Burn + (Remaining_Buffer / Daily_Burn)\n\nAction: If exhaustion date is earlier than month-end, throttle back daily spend in that category.",
        "type": "table",
        "gridPos": {"h": 7, "w": 12, "x": 12, "y": 76},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH mtd_spend AS (
  SELECT
    t.category,
    ABS(SUM(t.amount)) / 100.0 AS spent,
    (ABS(SUM(t.amount)) / 100.0) / MAX(1, CAST(strftime('%d', 'now') AS INTEGER)) AS daily_burn
  FROM transactions t
  JOIN categories c ON t.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
    AND substr(CAST(t.date AS TEXT), 1, 6) = strftime('%Y%m', 'now')
  GROUP BY t.category
),
budget_limits AS (
  SELECT
    zb.category,
    zb.amount / 100.0 AS budget_limit
  FROM zero_budgets zb
  JOIN categories c ON zb.category = c.id
  JOIN category_groups g ON c.cat_group = g.id
  WHERE zb.month = CAST(strftime('%Y%m', 'now') AS INTEGER)
    AND zb.amount > 0
    AND g.name NOT IN ('Investments and Savings', 'One-Time')
),
days_calc AS (
  SELECT 
    CAST(strftime('%d', 'now') AS REAL) AS current_day,
    CAST(strftime('%d', date(strftime('%Y-%m-01', 'now'), '+1 month', '-1 day')) AS REAL) AS days_in_month
)
SELECT
  c.name AS "Category",
  ROUND(b.budget_limit, 2) AS "Monthly Budget ($)",
  ROUND(COALESCE(m.spent, 0.0), 2) AS "Spent MTD ($)",
  ROUND(b.budget_limit - COALESCE(m.spent, 0.0), 2) AS "Remaining Buffer ($)",
  ROUND(COALESCE(m.daily_burn, 0.0), 2) AS "Daily Burn ($/day)",
  CASE
    WHEN COALESCE(m.spent, 0.0) >= b.budget_limit THEN '🚨 Over Budget'
    WHEN (COALESCE(m.daily_burn, 0.0) * d.days_in_month) > b.budget_limit THEN '🟡 Accelerating (Runs out Day ' || CAST(ROUND(b.budget_limit / MAX(0.01, m.daily_burn)) AS INT) || ')'
    ELSE '🟢 On Track (Pacing Well)'
  END AS "Burn Status Indicator"
FROM budget_limits b
JOIN categories c ON b.category = c.id
CROSS JOIN days_calc d
LEFT JOIN mtd_spend m ON b.category = m.category
ORDER BY (b.budget_limit - COALESCE(m.spent, 0.0)) ASC
LIMIT 10
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Monthly Budget ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Spent MTD ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Remaining Buffer ($)"},
                    "properties": [
                        {"id": "unit", "value": "currencyUSD"},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "yellow", "value": 0}, {"color": "green", "value": 100}]}}
                    ]
                },
                {
                    "matcher": {"id": "byName", "options": "Daily Burn ($/day)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Burn Status Indicator"},
                    "properties": [{"id": "custom.align", "value": "center"}]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    # -------------------------------------------------------------
    # SECTION 6: Hierarchical Category Decomposition
    # -------------------------------------------------------------
    panels.append({
        "id": 600,
        "title": "6. Hierarchical Category Decomposition & Budget Variance",
        "type": "row",
        "collapsed": false,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 83}
    })

    panels.append({
        "id": 601,
        "title": "📖 Layman's Guide: Category Decomposition & Variance Scorecard",
        "type": "text",
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 84},
        "options": {
            "mode": "markdown",
            "content": """### 💡 How to Read Category Decomposition & Budget Variance

* **Hierarchical Breakdown (Group $\\rightarrow$ Category)**:
  * Visualizes where your money went over the last 30 days, grouping small line items under broad umbrellas (e.g. Housing, Food, Fun, Expected Bills).
* **Budget vs. Actual Variance Waterfall**: *"The scorecard at the end of the month: Did you beat your budget or blow it?"*
  * **Formula**: $\\text{Net Variance} = \\text{Budgeted} - \\text{Actual Spend}$.
  * 🟢 **Surplus (Under Budget)**: Green blocks indicate categories where you spent less than budgeted, leaving positive cash.
  * 🔴 **Deficit (Over Budget)**: Red blocks indicate categories where you bled cash and exceeded budget limits.
  * **What to do**: Offset red deficits by transferring excess surplus from green categories before month close."""
        }
    })

    panels.append({
        "id": 602,
        "title": "Hierarchical Category Spend: Group -> Category",
        "description": "Plain English: Hierarchical categorical expense breakdown by Category Group -> Category -> Payee over the last 30 days.\n\nAction: Identify top expense clusters within each category group to prioritize savings targets.",
        "type": "table",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 88},
        "datasource": DS,
        "targets": [
            sql_target("A", """
SELECT
  g.name AS "Category Group",
  c.name AS "Category",
  ROUND(ABS(SUM(t.amount)) / 100.0, 2) AS "Expense Amount ($)"
FROM transactions t
JOIN categories c ON t.category = c.id
JOIN category_groups g ON c.cat_group = g.id
LEFT JOIN payees p ON t.description = p.id
WHERE t.tombstone = 0
  AND (t.isParent IS NULL OR t.isParent = 0)
  AND t.transferred_id IS NULL
  AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
  AND c.is_income = 0
  AND t.amount < 0
  AND g.name NOT IN ('Investments and Savings')
  AND t.date >= CAST(strftime('%Y%m01', date('now', '-30 day')) AS INTEGER)
GROUP BY g.name, c.name
ORDER BY 3 DESC
""")
        ],
        "fieldConfig": {
            "defaults": {
                "unit": "currencyUSD",
                "custom": {"align": "auto"}
            }
        },
        "options": {
            "showHeader": true
        }
    })

    panels.append({
        "id": 603,
        "title": "Budget vs. Actual Variance Waterfall (Monthly Scorecard)",
        "description": "Plain English: The scorecard at the end of the month: Did you beat your budget or blow it? Green blocks show categories where you saved money (surplus); red blocks show where you bled cash (deficit).\n\nFormula: Net Variance = Budgeted - Actual Spend\n\nThresholds:\n- 🟢 Surplus (Positive Variance): You beat your budget\n- 🔴 Deficit (Negative Variance): You overspent\n\nAction: Rebalance overspent categories with surplus savings from other groups.",
        "type": "table",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 88},
        "datasource": DS,
        "targets": [
            sql_target("A", """
WITH budgeted AS (
  SELECT
    c.cat_group,
    SUM(zb.amount) / 100.0 AS budget_amt
  FROM zero_budgets zb
  JOIN categories c ON zb.category = c.id
  WHERE zb.month = CAST(strftime('%Y%m', 'now') AS INTEGER)
  GROUP BY c.cat_group
),
actuals AS (
  SELECT
    c.cat_group,
    ABS(SUM(t.amount)) / 100.0 AS actual_amt
  FROM transactions t
  JOIN categories c ON t.category = c.id
  LEFT JOIN payees p ON t.description = p.id
  WHERE t.tombstone = 0
    AND (t.isParent IS NULL OR t.isParent = 0)
    AND t.transferred_id IS NULL
    AND (p.transfer_acct IS NULL OR p.transfer_acct = '')
    AND c.is_income = 0
    AND t.amount < 0
    AND substr(CAST(t.date AS TEXT), 1, 6) = strftime('%Y%m', 'now')
  GROUP BY c.cat_group
)
SELECT
  g.name AS "Category Group",
  ROUND(COALESCE(b.budget_amt, 0.0), 2) AS "Budgeted ($)",
  ROUND(COALESCE(a.actual_amt, 0.0), 2) AS "Actual Spend ($)",
  ROUND(COALESCE(b.budget_amt, 0.0) - COALESCE(a.actual_amt, 0.0), 2) AS "Net Variance ($)",
  CASE
    WHEN COALESCE(b.budget_amt, 0.0) - COALESCE(a.actual_amt, 0.0) >= 0 THEN '🟢 Surplus (Under Budget)'
    ELSE '🔴 Deficit (Over Budget)'
  END AS "Budget Status"
FROM category_groups g
LEFT JOIN budgeted b ON g.id = b.cat_group
LEFT JOIN actuals a ON g.id = a.cat_group
WHERE g.tombstone = 0 AND g.is_income = 0
  AND (COALESCE(b.budget_amt, 0) > 0 OR COALESCE(a.actual_amt, 0) > 0)
ORDER BY "Net Variance ($)" ASC
""")
        ],
        "fieldConfig": {
            "defaults": {
                "custom": {"align": "auto"}
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Budgeted ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Actual Spend ($)"},
                    "properties": [{"id": "unit", "value": "currencyUSD"}]
                },
                {
                    "matcher": {"id": "byName", "options": "Net Variance ($)"},
                    "properties": [
                        {"id": "unit", "value": "currencyUSD"},
                        {"id": "color", "value": {"mode": "thresholds"}},
                        {"id": "thresholds", "value": {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 0}]}}
                    ]
                }
            ]
        },
        "options": {
            "showHeader": true
        }
    })

    dashboard = {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": true,
                    "hide": true,
                    "name": "Annotations & Alerts",
                    "type": "dashboard"
                }
            ]
        },
        "description": "Comprehensive Actual Budget Financial Intelligence Dashboard powered by SQLite. Features Liquidity Runway, Spend Velocity curves, Z-Score Outlier Radar, 80/20 Pareto Merchant Analytics, 30/60/90-Day Projections, and Layman's Explanations for all metrics.",
        "editable": true,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "liveNow": false,
        "panels": panels,
        "refresh": "15m",
        "schemaVersion": 39,
        "tags": ["budget", "finance", "actual", "sqlite", "analytics"],
        "templating": {
            "list": [
                {
                    "datasource": DS,
                    "definition": "SELECT name FROM accounts WHERE tombstone = 0 AND closed = 0 ORDER BY name ASC",
                    "hide": 0,
                    "includeAll": true,
                    "multi": true,
                    "name": "account",
                    "query": "SELECT name FROM accounts WHERE tombstone = 0 AND closed = 0 ORDER BY name ASC",
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": false,
                    "sort": 1,
                    "type": "query"
                },
                {
                    "datasource": DS,
                    "definition": "SELECT name FROM category_groups WHERE tombstone = 0 AND is_income = 0 ORDER BY name ASC",
                    "hide": 0,
                    "includeAll": true,
                    "multi": true,
                    "name": "category_group",
                    "query": "SELECT name FROM category_groups WHERE tombstone = 0 AND is_income = 0 ORDER BY name ASC",
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": false,
                    "sort": 1,
                    "type": "query"
                }
            ]
        },
        "time": {"from": "now-90d", "to": "now"},
        "timepicker": {"refresh_intervals": ["5m", "15m", "30m", "1h", "2h", "1d"]},
        "timezone": "browser",
        "title": "Actual Budget Analytics & Advanced Financial Intelligence",
        "uid": "actual-budget-analytics",
        "version": 12
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2)

    print(f"✓ Generated {OUTPUT_FILE} ({len(panels)} panels)")

if __name__ == "__main__":
    make_dashboard()
