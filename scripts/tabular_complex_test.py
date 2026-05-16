#!/usr/bin/env python3
"""
Cortex KB — Complex NL2SQL stress test.

Uploads a rich CSV dataset and fires 25 hard queries covering:
  - Multi-level GROUP BY / HAVING
  - Window functions (RANK, LAG, running totals)
  - CTEs / subqueries
  - Date arithmetic
  - CASE WHEN / conditional aggregations
  - Top-N per group
  - Percentage / ratio calculations
  - String pattern matching
  - NULL handling
  - Cross-metric comparisons

For each query:
  - Records PASS / FAIL / RETRY
  - On failure: shows the SQL and error (does NOT exit early)
  - Retries driven by engine (up to 2 auto-retries with LLM self-correction)
  - Prints full summary table at end

Usage:
    uv run python scripts/tabular_complex_test.py \\
      --base-url https://knowledge.basivo.in \\
      --api-key cortex_xxx
"""
import argparse
import io
import json
import os
import sys
import time
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# ── Load .env ─────────────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Colour ────────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"; RED   = "\033[91m"; YELLOW = "\033[93m"
CYAN   = "\033[96m"; BOLD  = "\033[1m";  RESET  = "\033[0m"
DIM    = "\033[2m"

def ok(m):   print(f"  {GREEN}✓{RESET}  {m}")
def fail(m): print(f"  {RED}✗{RESET}  {m}")
def info(m): print(f"  {CYAN}·{RESET}  {m}")
def warn(m): print(f"  {YELLOW}!{RESET}  {m}")
def section(t): print(f"\n{BOLD}{t}{RESET}")

# ── Rich dataset ──────────────────────────────────────────────────────────────
# 48 rows: 4 regions × 3 products × 4 quarters
# Columns: year, quarter, month, region, salesperson, product, category,
#          units_sold, unit_price, revenue, cost, discount_pct, returns, channel

CSV_CONTENT = b"""\
year,quarter,month,region,salesperson,product,category,units_sold,unit_price,revenue,cost,discount_pct,returns,channel
2024,Q1,2024-01,North,Alice,Widget Pro,Hardware,120,299.99,35998.80,18000,5,3,Online
2024,Q1,2024-01,North,Bob,Widget Lite,Hardware,200,149.99,29998.00,12000,0,5,Retail
2024,Q1,2024-01,North,Alice,SaaS Basic,Software,50,99.99,4999.50,500,10,0,Online
2024,Q1,2024-01,South,Carol,Widget Pro,Hardware,95,299.99,28499.05,14250,5,2,Retail
2024,Q1,2024-01,South,Dave,Widget Lite,Hardware,180,149.99,26998.20,10800,0,8,Online
2024,Q1,2024-01,South,Carol,SaaS Basic,Software,80,99.99,7999.20,800,10,0,Online
2024,Q1,2024-01,East,Eve,Widget Pro,Hardware,70,299.99,20999.30,10500,5,1,Online
2024,Q1,2024-01,East,Frank,Widget Lite,Hardware,110,149.99,16498.90,8800,0,4,Retail
2024,Q1,2024-01,East,Eve,SaaS Basic,Software,40,99.99,3999.60,400,10,0,Online
2024,Q1,2024-01,West,Grace,Widget Pro,Hardware,130,299.99,38998.70,19500,5,2,Retail
2024,Q1,2024-01,West,Heidi,Widget Lite,Hardware,160,149.99,23998.40,9600,0,3,Online
2024,Q1,2024-01,West,Grace,SaaS Basic,Software,60,99.99,5999.40,600,10,1,Online
2024,Q2,2024-04,North,Alice,Widget Pro,Hardware,140,299.99,41998.60,21000,5,4,Online
2024,Q2,2024-04,North,Bob,Widget Lite,Hardware,220,149.99,32997.80,13200,0,6,Retail
2024,Q2,2024-04,North,Alice,SaaS Basic,Software,70,99.99,6999.30,700,10,0,Online
2024,Q2,2024-04,South,Carol,Widget Pro,Hardware,100,299.99,29999.00,15000,5,3,Retail
2024,Q2,2024-04,South,Dave,Widget Lite,Hardware,195,149.99,29248.05,11700,0,7,Online
2024,Q2,2024-04,South,Carol,SaaS Basic,Software,90,99.99,8999.10,900,10,1,Online
2024,Q2,2024-04,East,Eve,Widget Pro,Hardware,85,299.99,25499.15,12750,5,2,Online
2024,Q2,2024-04,East,Frank,Widget Lite,Hardware,125,149.99,18748.75,10000,0,5,Retail
2024,Q2,2024-04,East,Eve,SaaS Basic,Software,55,99.99,5499.45,550,10,0,Online
2024,Q2,2024-04,West,Grace,Widget Pro,Hardware,150,299.99,44998.50,22500,5,3,Retail
2024,Q2,2024-04,West,Heidi,Widget Lite,Hardware,175,149.99,26248.25,10500,0,4,Online
2024,Q2,2024-04,West,Grace,SaaS Basic,Software,65,99.99,6499.35,650,10,0,Online
2024,Q3,2024-07,North,Alice,Widget Pro,Hardware,160,299.99,47998.40,24000,5,5,Online
2024,Q3,2024-07,North,Bob,Widget Lite,Hardware,240,149.99,35997.60,14400,0,7,Retail
2024,Q3,2024-07,North,Alice,SaaS Basic,Software,85,99.99,8499.15,850,10,0,Online
2024,Q3,2024-07,South,Carol,Widget Pro,Hardware,110,299.99,32998.90,16500,5,4,Retail
2024,Q3,2024-07,South,Dave,Widget Lite,Hardware,205,149.99,30747.95,12300,0,9,Online
2024,Q3,2024-07,South,Carol,SaaS Basic,Software,95,99.99,9499.05,950,10,1,Online
2024,Q3,2024-07,East,Eve,Widget Pro,Hardware,90,299.99,26999.10,13500,5,2,Online
2024,Q3,2024-07,East,Frank,Widget Lite,Hardware,135,149.99,20248.65,10800,0,5,Retail
2024,Q3,2024-07,East,Eve,SaaS Basic,Software,60,99.99,5999.40,600,10,0,Online
2024,Q3,2024-07,West,Grace,Widget Pro,Hardware,170,299.99,50998.30,25500,5,4,Retail
2024,Q3,2024-07,West,Heidi,Widget Lite,Hardware,190,149.99,28498.10,11400,0,5,Online
2024,Q3,2024-07,West,Grace,SaaS Basic,Software,75,99.99,7499.25,750,10,1,Online
2024,Q4,2024-10,North,Alice,Widget Pro,Hardware,180,299.99,53998.20,27000,5,6,Online
2024,Q4,2024-10,North,Bob,Widget Lite,Hardware,260,149.99,38997.40,15600,0,8,Retail
2024,Q4,2024-10,North,Alice,SaaS Basic,Software,100,99.99,9999.00,1000,10,0,Online
2024,Q4,2024-10,South,Carol,Widget Pro,Hardware,125,299.99,37498.75,18750,5,5,Retail
2024,Q4,2024-10,South,Dave,Widget Lite,Hardware,215,149.99,32247.85,12900,0,10,Online
2024,Q4,2024-10,South,Carol,SaaS Basic,Software,105,99.99,10498.95,1050,10,2,Online
2024,Q4,2024-10,East,Eve,Widget Pro,Hardware,100,299.99,29999.00,15000,5,3,Online
2024,Q4,2024-10,East,Frank,Widget Lite,Hardware,145,149.99,21748.55,11600,0,6,Retail
2024,Q4,2024-10,East,Eve,SaaS Basic,Software,70,99.99,6999.30,700,10,0,Online
2024,Q4,2024-10,West,Grace,Widget Pro,Hardware,190,299.99,56998.10,28500,5,5,Retail
2024,Q4,2024-10,West,Heidi,Widget Lite,Hardware,200,149.99,29998.00,12000,0,6,Online
2024,Q4,2024-10,West,Grace,SaaS Basic,Software,80,99.99,7999.20,800,10,1,Online
"""

# ── Test cases ────────────────────────────────────────────────────────────────

@dataclass
class Case:
    id: str
    query: str
    description: str
    # Optional: callable(text) -> bool for result validation
    validate: object = None

CASES = [
    Case("C01", "What is the total revenue by region?",
         "Basic GROUP BY + SUM",
         lambda t: all(r in t for r in ["North","South","East","West"])),

    Case("C02", "Show quarterly revenue trend — total revenue per quarter ordered by quarter",
         "ORDER BY time dimension",
         lambda t: "Q1" in t and "Q2" in t),

    Case("C03", "Who are the top 3 salespersons by total revenue?",
         "TOP-N with ORDER BY + LIMIT",
         lambda t: any(n in t for n in ["Alice","Carol","Grace"])),

    Case("C04", "What is the gross profit margin percentage per product? (revenue - cost) / revenue * 100",
         "Computed ratio / percentage",
         lambda t: "%" in t or any(x in t for x in ["Widget Pro","Widget Lite","SaaS"])),

    Case("C05", "Which region-product combinations had revenue above 100000 in total?",
         "HAVING clause filter",
         lambda t: "|" in t),

    Case("C06", "Show running total of revenue by quarter (cumulative sum ordered by quarter)",
         "Window function — running SUM",
         lambda t: "|" in t),

    Case("C07", "Rank salespersons by total revenue within each region using RANK()",
         "Window RANK() PARTITION BY",
         lambda t: "|" in t),

    Case("C08", "What is the quarter-over-quarter revenue growth rate for each region?",
         "LAG() window function / QoQ growth",
         lambda t: "|" in t),

    Case("C09", "Using a CTE, find the average revenue per salesperson then return only those above the average",
         "CTE + subquery filter",
         lambda t: "|" in t),

    Case("C10", "Show total units sold and total returns by product category, with return rate as percentage",
         "Multi-aggregation + computed column",
         lambda t: "Hardware" in t or "Software" in t),

    Case("C11", "Which salesperson had the highest revenue in Q3 2024?",
         "Date/quarter filter + MAX",
         lambda t: any(n in t for n in ["Alice","Carol","Grace","Dave","Eve","Frank","Heidi","Bob"])),

    Case("C12", "Compare Online vs Retail channel: total revenue, units sold, and avg discount per channel",
         "GROUP BY channel multi-metric",
         lambda t: "Online" in t and "Retail" in t),

    Case("C13", "What percentage of total annual revenue came from the Software category?",
         "Percentage of total (subquery or CTE)",
         lambda t: "|" in t),

    Case("C14", "Show the month with the highest revenue for each region",
         "TOP-1 per group (window or subquery)",
         lambda t: all(r in t for r in ["North","South","East","West"])),

    Case("C15", "Calculate the revenue-to-cost ratio for each salesperson, show only ratios above 2.0",
         "HAVING on computed ratio",
         lambda t: "|" in t),

    Case("C16", "What is the total discount given in dollar terms? (revenue * discount_pct / 100)",
         "Computed dollar discount",
         lambda t: "|" in t),

    Case("C17", "Show products ranked by average discount percentage, highest first",
         "AVG + ORDER BY DESC",
         lambda t: "SaaS" in t or "Widget" in t),

    Case("C18", "Find salespersons who sold in all 4 quarters (appeared in all quarters)",
         "HAVING COUNT(DISTINCT ...) = 4",
         lambda t: "|" in t),

    Case("C19", "Show revenue breakdown by region and channel (pivot-style: region rows, channel columns)",
         "Conditional aggregation / pivot",
         lambda t: "online" in t.lower() or "retail" in t.lower()),

    Case("C20", "What is the net revenue per quarter (revenue minus returns value, assuming return value = unit_price * returns)?",
         "Multi-column arithmetic",
         lambda t: "|" in t),

    Case("C21", "Find the top product by revenue in each quarter",
         "TOP-1 per group using window function or subquery",
         lambda t: "|" in t),

    Case("C22", "Which salesperson improved revenue the most from Q1 to Q4?",
         "Self-join or PIVOT on quarters",
         lambda t: "|" in t),

    Case("C23", "Show the 3-month moving average of revenue (by month, all regions combined)",
         "Rolling average using window function",
         lambda t: "|" in t),

    Case("C24", "What fraction of rows have a non-zero discount? Show as a percentage",
         "COUNT FILTER / conditional fraction",
         lambda t: "|" in t or "%" in t),

    Case("C25", "Summarize: total revenue, total cost, total profit, profit margin %, total units, avg deal size (revenue/units) — all in one row",
         "Single-row KPI summary",
         lambda t: "|" in t),
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def hdr(k): return {"X-Api-Key": k}

def upload(c, base, key, name, data, mime):
    r = c.post(f"{base}/ingest/upload", files={"file": (name, data, mime)}, headers=hdr(key))
    if r.status_code == 409:
        doc_id = r.json().get("document_id") or r.json().get("detail","").split(": ")[-1]
        warn(f"Already exists → {doc_id}")
        return doc_id
    if r.status_code not in (200,201,202):
        print(f"{RED}Upload failed {r.status_code}: {r.text[:200]}{RESET}"); sys.exit(1)
    doc_id = r.json()["document_id"]
    ok(f"Uploaded {name} → {doc_id}")
    return doc_id

def poll(c, base, key, doc_id, timeout=180):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        r = c.get(f"{base}/status/{doc_id}", headers=hdr(key))
        if r.status_code == 200:
            s = r.json().get("overall_status","?")
            if s != last: info(f"  status={s}"); last=s
            if s == "indexed": return
            if "fail" in s or "error" in s:
                print(f"{RED}Pipeline failed: {s}{RESET}"); sys.exit(1)
        time.sleep(4)
    print(f"{RED}Timeout waiting for indexed{RESET}"); sys.exit(1)

def search(c, base, key, query, doc_id):
    r = c.post(f"{base}/search",
               json={"query": query, "mode": "hybrid", "top_k": 5, "document_id": doc_id},
               headers=hdr(key))
    if r.status_code != 200:
        return []
    return r.json().get("results", [])

# ── Result helpers ────────────────────────────────────────────────────────────

@dataclass
class Result:
    case_id: str
    description: str
    status: str          # PASS / FAIL / NO_RESULT / VALIDATION_FAIL
    sql: str = ""
    text: str = ""
    retried: bool = False
    error: str = ""
    duration_ms: float = 0.0

def run_case(c, base, key, case: Case, doc_id: str) -> Result:
    t0 = time.time()
    results = search(c, base, key, case.query, doc_id)
    duration = (time.time() - t0) * 1000

    if not results:
        return Result(case.id, case.description, "NO_RESULT", duration_ms=duration)

    tabular = [r for r in results if r.get("result_type") == "tabular"]
    if not tabular:
        return Result(case.id, case.description, "NO_RESULT",
                      text=results[0].get("text","")[:200], duration_ms=duration)

    top = tabular[0]
    text  = top.get("text", "")
    sql   = top.get("sql_query", "")

    # Detect if engine auto-retried (sql contains comment or differs from simple)
    retried = "retry" in text.lower() or "fix" in sql.lower()

    # Check for execution failure marker
    if text.startswith("_SQL execution failed"):
        return Result(case.id, case.description, "FAIL",
                      sql=sql, text=text[:300], duration_ms=duration,
                      error=text[:200])

    if text.startswith("_Could not") or text.startswith("_Generated SQL was rejected"):
        return Result(case.id, case.description, "FAIL",
                      sql=sql, text=text[:300], duration_ms=duration,
                      error=text[:200])

    # Optional validator
    if case.validate and not case.validate(text):
        return Result(case.id, case.description, "VALIDATION_FAIL",
                      sql=sql, text=text, duration_ms=duration)

    return Result(case.id, case.description, "PASS",
                  sql=sql, text=text, retried=retried, duration_ms=duration)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--filter", help="Run only cases whose ID contains this string (e.g. C06)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    section("SQL Provider")
    info(f"BASE_URL = {os.getenv('TABULAR_SQL_BASE_URL','(ollama)')}")
    info(f"MODEL    = {os.getenv('TABULAR_SQL_MODEL','qwen2.5:7b')}")

    cases = CASES
    if args.filter:
        cases = [c for c in cases if args.filter.upper() in c.id.upper()]
        info(f"Filtered to {len(cases)} case(s) matching {args.filter!r}")

    with httpx.Client(timeout=90.0, verify=False) as client:

        # Health
        section("Health")
        r = client.get(f"{base}/health")
        if r.status_code != 200: print(f"{RED}Server down{RESET}"); sys.exit(1)
        ok(f"Server healthy")

        # Upload
        section("Upload Dataset")
        doc_id = upload(client, base, args.api_key, "complex_sales.csv", CSV_CONTENT, "text/csv")

        # Poll
        section("Pipeline")
        poll(client, base, args.api_key, doc_id, args.timeout)
        ok("Indexed and ready")

        # Run cases
        section(f"Running {len(cases)} Complex NL2SQL Queries")
        results: list[Result] = []

        for case in cases:
            print(f"\n  {BOLD}[{case.id}]{RESET} {case.query[:80]}")
            info(f"  Type: {case.description}")
            res = run_case(client, base, args.api_key, case, doc_id)
            results.append(res)

            if res.status == "PASS":
                ok(f"  PASS  ({res.duration_ms:.0f}ms)")
                if res.sql:
                    info(f"  SQL: {res.sql[:100].strip()}")
                # Show first 2 data rows
                lines = [l for l in res.text.splitlines() if l.startswith("|")]
                preview = "\n".join(lines[:4])
                if preview:
                    info(f"  Result:\n{textwrap.indent(preview, '    ')}")
            elif res.status == "VALIDATION_FAIL":
                warn(f"  VALIDATION FAIL — result didn't contain expected keywords")
                if res.sql: warn(f"  SQL: {res.sql[:120]}")
                warn(f"  Got: {res.text[:200]}")
            else:
                fail(f"  {res.status}  ({res.duration_ms:.0f}ms)")
                if res.sql: fail(f"  SQL: {res.sql[:120]}")
                if res.error: fail(f"  Error: {res.error[:150]}")

        # Cleanup
        if not args.no_cleanup:
            section("Cleanup")
            r = client.delete(f"{base}/documents/{doc_id}", headers=hdr(args.api_key))
            if r.status_code in (200,202,204): ok(f"Deleted {doc_id}")
            else: warn(f"Delete returned {r.status_code}")

        # Summary
        section("━━  RESULTS SUMMARY  ━━")
        pass_n  = sum(1 for r in results if r.status == "PASS")
        fail_n  = sum(1 for r in results if r.status == "FAIL")
        val_n   = sum(1 for r in results if r.status == "VALIDATION_FAIL")
        none_n  = sum(1 for r in results if r.status == "NO_RESULT")
        total   = len(results)
        avg_ms  = sum(r.duration_ms for r in results) / total if total else 0

        print(f"\n  {'ID':<5} {'Status':<18} {'ms':>6}  Description")
        print(f"  {'─'*5} {'─'*18} {'─'*6}  {'─'*40}")
        for r in results:
            colour = GREEN if r.status=="PASS" else (YELLOW if r.status=="VALIDATION_FAIL" else RED)
            flag   = " ↺" if r.retried else ""
            print(f"  {r.case_id:<5} {colour}{r.status+flag:<18}{RESET} {r.duration_ms:>6.0f}  {r.description}")

        print(f"""
  {BOLD}Total : {total}{RESET}
  {GREEN}PASS  : {pass_n}{RESET}
  {YELLOW}VAL   : {val_n}{RESET}  (result returned but keyword check failed)
  {RED}FAIL  : {fail_n}{RESET}
  {RED}NONE  : {none_n}{RESET}  (no tabular result returned)
  Avg latency : {avg_ms:.0f}ms
""")
        if pass_n == total:
            print(f"{GREEN}{BOLD}  All {total} complex queries passed ✓{RESET}\n")
        else:
            print(f"{YELLOW}{BOLD}  {pass_n}/{total} passed — {fail_n+val_n+none_n} need attention{RESET}\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
