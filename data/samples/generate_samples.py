"""
Generate three sample SOV files for testing:
  1. Standard SOV (clean)
  2. Messy SOV (bad headers, currency symbols, merged cells)
  3. Multi-sheet SOV (with noise sheets)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import openpyxl
from openpyxl.utils import get_column_letter
import random
import string


def make_sample_1():
    """Clean SOV with standard headers."""
    data = {
        "Loc #": ["LOC-001", "LOC-002", "LOC-003", "LOC-004", "LOC-005"],
        "Street Address": ["123 Main St", "456 Oak Ave", "789 Pine Rd", "321 Elm Blvd", "654 Maple Dr"],
        "City": ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"],
        "ST": ["NY", "CA", "IL", "TX", "AZ"],
        "Zip Code": [10001, 90001, 60601, 77001, 85001],
        "County": ["New York", "Los Angeles", "Cook", "Harris", "Maricopa"],
        "Country": ["USA", "USA", "USA", "USA", "USA"],
        "Bldg Repl Cost": [1500000.00, 2300000.00, 875000.00, 3200000.00, 650000.00],
        "Contents Value": [250000.00, 450000.00, 125000.00, 600000.00, 100000.00],
        "Business Interruption": [500000.00, 750000.00, 200000.00, 1000000.00, 150000.00],
        "Occ Code": ["Office", "Retail", "Warehouse", "Manufacturing", "Office"],
        "Const Type": ["Frame", "Masonry", "Steel", "Concrete", "Frame"],
        "Num Stories": [5, 3, 1, 8, 4],
        "# Buildings": [1, 1, 2, 1, 1],
        "Yr Blt": [1985, 2001, 1972, 2015, 1998],
        "Fire Prot": ["Y", "Y", "N", "Y13", "N"],
        "Other Insured Value": [None, None, 50000.00, None, 25000.00],
    }
    df = pd.DataFrame(data)
    path = "d:/Adrosonic/data/samples/sample1_standard.xlsx"
    df.to_excel(path, index=False)
    print(f"Created: {path}")
    return path


def make_sample_2():
    """Messy SOV with currency symbols, non-standard codes, metadata rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SOV Data"

    # Metadata rows
    ws["A1"] = "STATEMENT OF VALUES"
    ws["A2"] = "Client: Acme Corporation"
    ws["A3"] = "Effective Date: 01/01/2024"
    ws["A4"] = ""  # blank row

    # Headers at row 5
    headers = [
        "Reference No.", "Property Address", "City Name", "State",
        "Postal Code", "Building Value ($)", "Contents ($)", "BI Value",
        "Occupancy Type", "Construction", "Stories", "Bldgs",
        "Year Constructed", "Sprinklers Y/N", "Other Value"
    ]
    for j, h in enumerate(headers, start=1):
        ws.cell(row=5, column=j, value=h)

    # Data rows with messy values
    rows = [
        ["REF-2024-001", "100 Broadway", "New York", "New York", "10001",
         "$1,500,000", "$250,000", "500000", "Office", "Frame", 5, 1, 1985, "Yes", None],
        ["REF-2024-002", "200 Sunset Blvd", "Los Angeles", "CA", "90001",
         "$2,300,000.00", "$450,000", "750000", "Retail", "Masonry", 3, 1, 2001, "Y", None],
        ["REF-2024-003", "300 Lakeshore Dr", "Chicago", "IL", "60601",
         "875000", "125000", "200000", "Warehouse", "Steel", 1, 2, 1972, "N", "$50,000"],
        ["REF-2024-004", "400 Texas Ave", "Houston", "TX", "77001",
         "$3,200,000", "($600,000)", "1000000", "Manufacturing", "Concrete", 8, 1, 2015, "Y13", None],
        ["REF-2024-005", "500 Desert Rd", "Phoenix", "AZ", "85001",
         "650000", "100000", "TBD", "Office", "Frame", 4, 1, 1998, "N", "25000"],
        ["REF-2024-001", "100 Broadway", "New York", "NY", "10001",  # Duplicate ref
         "$1,500,000", "$250,000", "500000", "Office", "Frame", 5, 1, 1985, "Y", None],
        # Total row
        ["TOTAL", "", "", "", "", "$10,125,000", "$1,775,000", "", "", "", "", "", "", "", ""],
    ]

    for i, row in enumerate(rows, start=6):
        for j, val in enumerate(row, start=1):
            ws.cell(row=i+1, column=j, value=val)  # offset by 1 for blank row

    # Merge some header cells
    ws.merge_cells("A1:O1")

    path = "d:/Adrosonic/data/samples/sample2_messy.xlsx"
    wb.save(path)
    print(f"Created: {path}")
    return path


def make_sample_3():
    """Multi-sheet Excel with noise sheets."""
    wb = openpyxl.Workbook()

    # Sheet 1: Summary/noise
    ws1 = wb.active
    ws1.title = "Summary"
    ws1["A1"] = "Portfolio Summary"
    ws1["A2"] = "Total TIV: $12,000,000"
    ws1["A3"] = "Locations: 5"

    # Sheet 2: SOV data
    ws2 = wb.create_sheet("SOV - 2024")
    headers = [
        "Location ID", "Address", "City", "State", "ZIP",
        "County", "Country", "Building RCV", "Contents",
        "Time Element", "Occupancy", "Construction",
        "Num Floors", "Number of Buildings", "Year Built",
        "Fire Sprinklers (Y/N)", "Other"
    ]
    for j, h in enumerate(headers, start=1):
        ws2.cell(row=1, column=j, value=h)

    sov_rows = [
        ["L001", "10 Park Ave", "New York", "NY", 10001, "New York", "USA",
         1200000, 200000, 400000, "Office", "Frame", 10, 1, 1990, "Y", None],
        ["L002", "20 Ocean Blvd", "Miami", "FL", 33101, "Miami-Dade", "USA",
         2500000, 500000, 800000, "Hotel", "Concrete", 15, 1, 2005, "Y13", None],
        ["L003", "30 Peach St", "Atlanta", "GA", 30301, "Fulton", "USA",
         750000, 150000, 250000, "Retail", "Masonry", 2, 3, 1985, "N", 50000],
        ["L004", "40 Music Row", "Nashville", "TN", 37201, "Davidson", "USA",
         900000, 200000, 300000, "Mixed Use", "Frame", 4, 1, 2010, "Y", None],
        ["L005", "50 Tech Blvd", "Austin", "TX", 78701, "Travis", "USA",
         3000000, 800000, 1200000, "Office", "Steel", 20, 1, 2018, "Y13", None],
    ]
    for i, row in enumerate(sov_rows, start=2):
        for j, val in enumerate(row, start=1):
            ws2.cell(row=i, column=j, value=val)

    # Sheet 3: Another noise sheet
    ws3 = wb.create_sheet("Notes")
    ws3["A1"] = "Underwriter Notes"
    ws3["A2"] = "Updated 2024-01-01"

    path = "d:/Adrosonic/data/samples/sample3_multisheet.xlsx"
    wb.save(path)
    print(f"Created: {path}")
    return path


if __name__ == "__main__":
    Path("d:/Adrosonic/data/samples").mkdir(parents=True, exist_ok=True)
    make_sample_1()
    make_sample_2()
    make_sample_3()
    print("All sample files created.")
