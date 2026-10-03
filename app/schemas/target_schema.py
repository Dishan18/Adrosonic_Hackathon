"""
Target schema definition: exactly 17 fields in exact order.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# The 17 canonical target fields in exact order (case-sensitive)
TARGET_FIELDS: List[str] = [
    "Reference",
    "Address",
    "City",
    "State",
    "Zip",
    "County",
    "Country",
    "Building Value",
    "Contents",
    "BI",
    "Occupancy",
    "Construction",
    "Storeys",
    "Number of Buildings",
    "Year Built",
    "Fire Sprinklers (Y/N)",
    "Other",
]

# Expected dtype for each field (for casting)
TARGET_DTYPES: Dict[str, str] = {
    "Reference": "str",
    "Address": "str",
    "City": "str",
    "State": "str",
    "Zip": "int",
    "County": "str",
    "Country": "str",
    "Building Value": "float",
    "Contents": "float",
    "BI": "float",
    "Occupancy": "str",
    "Construction": "str",
    "Storeys": "int",
    "Number of Buildings": "int",
    "Year Built": "int",
    "Fire Sprinklers (Y/N)": "str",
    "Other": "float",
}

# Human-readable field definitions (used in LLM prompts)
TARGET_DEFINITIONS: Dict[str, str] = {
    "Reference": "Unique identifier or reference number for the insured location or risk (e.g. policy/location ID, loc number).",
    "Address": "Street address of the insured property.",
    "City": "City where the insured property is located.",
    "State": "US state abbreviation (e.g. CA, TX, NY).",
    "Zip": "5-digit US postal code (integer).",
    "County": "County where the insured property is located.",
    "Country": "Country where the insured property is located (e.g. USA, US).",
    "Building Value": "Replacement cost value of the building/structure (currency, float). Also known as Building RCV, Bldg Repl Cost.",
    "Contents": "Insured value of contents within the building (currency, float). Also known as Contents Value.",
    "BI": "Business Interruption value (currency, float). Also known as Time Element, BI/EE.",
    "Occupancy": "Occupancy class or type of use (e.g. Office, Retail, Warehouse). May be a code.",
    "Construction": "Construction type of the building (e.g. Frame, Masonry, Steel). May be a code.",
    "Storeys": "Number of floors/storeys in the building (integer, typically 1–100).",
    "Number of Buildings": "Number of buildings at the location (integer, >= 1).",
    "Year Built": "Year the building was originally constructed (integer, 1700–current year).",
    "Fire Sprinklers (Y/N)": "Whether fire sprinklers are present. Valid values: Y, N, Y13, Y(13R), etc.",
    "Other": "Other/additional insured value not covered by Building, Contents, or BI (currency, float).",
}

# Synonyms / common abbreviations used in fuzzy/semantic matching
TARGET_SYNONYMS: Dict[str, List[str]] = {
    "Reference": ["Ref", "Loc #", "Location #", "Loc No", "Location No", "Location ID", "Loc ID", "Pol No", "Policy No", "Site ID", "Risk ID", "Item No", "Item #", "Loc Num", "Location Number"],
    "Address": ["Street", "Street Address", "Addr", "Property Address", "Site Address", "Location Address"],
    "City": ["City Name", "Town", "Municipality", "Locality"],
    "State": ["ST", "Province", "St.", "State Code"],
    "Zip": ["ZIP Code", "Postal Code", "Zip Code", "Post Code", "Zipcode", "Zip+4", "Zip Code (5 digit)"],
    "County": ["Parish", "Borough", "District"],
    "Country": ["Nation", "Country Code", "Country Name", "Ctry"],
    "Building Value": ["Building", "Building Values", "Bldg Value", "Bldg Repl Cost", "Building RCV", "Bldg RCV", "Replacement Cost", "TIV-Bldg", "Building TIV", "Structure Value", "Bldg Val"],
    "Contents": ["Contents Value", "Cont Value", "Contents TIV", "TIV-Contents", "Personal Property", "Business Personal Property", "BPP"],
    "BI": ["Business Interruption", "Business Interruption Value", "BI Value", "Time Element", "BI/EE", "BI EE", "Business Income", "Extra Expense", "Loss of Rents", "Rental Value"],
    "Occupancy": ["Occ", "Occ Code", "Occupancy Class", "Use", "Building Use", "Property Type", "Occ Type"],
    "Construction": ["Const", "Const Code", "Construction Type", "Build Type", "Frame Type", "ISO Construction"],
    "Storeys": ["Stories", "Floors", "No of Floors", "Num Floors", "Num Stories", "No of Stories", "# of Stories", "Number of Stories", "Num of Storeys", "Floor Count", "# Floors", "# Floor"],
    "Number of Buildings": ["Num Bldgs", "# Bldgs", "No of Bldgs", "Bldg Count", "No of Buildings", "# of Buildings", "Num Buildings", "Building Count"],
    "Year Built": ["Yr Blt", "Yr Built", "Year of Construction", "Built Year", "Construct Year", "Build Year", "Year Constructed"],
    "Fire Sprinklers (Y/N)": ["Fire Prot", "Fire Protection", "Sprinklers", "Sprinkler", "Sprinklered", "% Sprinklered", "Sprinkler %", "Fire Sprinkler", "Sprinkler System", "SPRK", "Sprink", "Fire Prot.", "Sprk Sys"],
    "Other": ["Other Value", "Other TIV", "Misc Value", "Miscellaneous", "Other Covered", "Add'l Value"],
}

# Monetary fields (expect float / currency-formatted numbers)
MONETARY_FIELDS = {"Building Value", "Contents", "BI", "Other"}

# Integer fields
INTEGER_FIELDS = {"Zip", "Storeys", "Number of Buildings", "Year Built"}

# String fields
STRING_FIELDS = {"Reference", "Address", "City", "State", "County", "Country",
                 "Occupancy", "Construction", "Fire Sprinklers (Y/N)"}

# Valid canonical sprinkler codes (normalized form)
# Values like YES, NO, True, 1, 0 need normalization first
VALID_SPRINKLER_CODES = {"Y", "N", "Y13", "Y(13R)"}

# Accepted (non-canonical) sprinkler codes that require normalization
NORMALIZABLE_SPRINKLER_CODES = {"YES", "NO", "TRUE", "FALSE", "1", "0"}

# US State abbreviations
US_STATE_ABBREVS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP",
}
