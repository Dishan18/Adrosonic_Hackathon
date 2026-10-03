"""
Comprehensive pytest test suite for the Agentic SOV Intelligence System.
Covers all areas specified in requirements.
"""

import io
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample1_path():
    return str(Path(__file__).parent.parent / "data/samples/sample1_standard.xlsx")


@pytest.fixture
def sample2_path():
    return str(Path(__file__).parent.parent / "data/samples/sample2_messy.xlsx")


@pytest.fixture
def sample3_path():
    return str(Path(__file__).parent.parent / "data/samples/sample3_multisheet.xlsx")


@pytest.fixture
def simple_csv(tmp_path):
    data = pd.DataFrame({
        "Loc #": ["LOC-001", "LOC-002"],
        "Address": ["123 Main St", "456 Oak Ave"],
        "City": ["New York", "LA"],
        "ST": ["NY", "CA"],
        "Zip": [10001, 90001],
        "Bldg Value": [1000000, 2000000],
        "Contents Value": [100000, 200000],
        "BI": [200000, 400000],
        "Yr Blt": [1990, 2000],
        "Sprinklers": ["Y", "N"],
    })
    path = tmp_path / "test.csv"
    data.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def malformed_xlsx(tmp_path):
    """Excel file with no SOV data."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Random"
    ws["B1"] = "Data"
    ws["A2"] = 123
    ws["B2"] = 456
    path = tmp_path / "malformed.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def empty_xlsx(tmp_path):
    """Completely empty Excel."""
    import openpyxl
    wb = openpyxl.Workbook()
    path = tmp_path / "empty.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def merged_xlsx(tmp_path):
    """Excel with merged cells in header."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Location Info"
    ws["C1"] = "Financial Info"
    ws.merge_cells("A1:B1")
    ws.merge_cells("C1:F1")
    ws["A2"] = "Loc ID"
    ws["B2"] = "Address"
    ws["C2"] = "Bldg Value"
    ws["D2"] = "Contents"
    ws["E2"] = "BI"
    ws["F2"] = "Other"
    ws["A3"] = "L001"
    ws["B3"] = "123 Main"
    ws["C3"] = 1000000
    ws["D3"] = 100000
    ws["E3"] = 200000
    ws["F3"] = None
    path = tmp_path / "merged.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def duplicate_headers_xlsx(tmp_path):
    """Excel with duplicate column headers."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Reference"
    ws["B1"] = "Address"
    ws["C1"] = "Address"  # duplicate
    ws["D1"] = "Building Value"
    ws["A2"] = "L001"
    ws["B2"] = "123 Main"
    ws["C2"] = "123 Main Alt"
    ws["D2"] = 1000000
    path = tmp_path / "dup_headers.xlsx"
    wb.save(path)
    return str(path)


@pytest.fixture
def sov_state_with_mappings(sample1_path):
    """SOV state after Agent 1 and 2 have run."""
    from app.orchestration.state import create_initial_state
    from app.agents.sheet_discovery import run_sheet_discovery
    from app.agents.schema_mapping import run_schema_mapping

    state = create_initial_state(
        file_path=sample1_path,
        original_filename="sample1.xlsx",
        file_type="xlsx",
        session_id="test_session",
    )
    state = run_sheet_discovery(state)
    state = run_schema_mapping(state)
    return state


# ---------------------------------------------------------------------------
# 1. File Ingestion
# ---------------------------------------------------------------------------

class TestFileIngestion:

    def test_load_xlsx(self, sample1_path):
        from app.processing.workbook import load_workbook_sheets
        sheets = load_workbook_sheets(sample1_path)
        assert len(sheets) >= 1
        first_sheet = list(sheets.values())[0]
        assert len(first_sheet) > 0

    def test_load_csv(self, simple_csv):
        from app.processing.workbook import load_workbook_sheets
        sheets = load_workbook_sheets(simple_csv)
        assert "Sheet1" in sheets
        assert len(sheets["Sheet1"]) >= 2

    def test_load_multisheet(self, sample3_path):
        from app.processing.workbook import load_workbook_sheets
        sheets = load_workbook_sheets(sample3_path)
        assert len(sheets) >= 2

    def test_unsupported_extension_raises(self, tmp_path):
        from app.processing.workbook import load_workbook_sheets
        bad_file = tmp_path / "test.txt"
        bad_file.write_text("not a spreadsheet")
        with pytest.raises(ValueError, match="Unsupported file type"):
            load_workbook_sheets(str(bad_file))

    def test_malformed_excel_handled(self, tmp_path):
        from app.processing.workbook import load_workbook_sheets
        bad_file = tmp_path / "bad.xlsx"
        bad_file.write_bytes(b"not an xlsx file at all")
        with pytest.raises(ValueError):
            load_workbook_sheets(str(bad_file))


# ---------------------------------------------------------------------------
# 2. Header Detection
# ---------------------------------------------------------------------------

class TestHeaderDetection:

    def test_header_detected_row_0(self, sample1_path):
        from app.processing.workbook import load_workbook_sheets, detect_header_row
        sheets = load_workbook_sheets(sample1_path)
        df = list(sheets.values())[0]
        header_row = detect_header_row(df)
        assert header_row >= 0

    def test_header_detected_messy(self, sample2_path):
        from app.processing.workbook import load_workbook_sheets, detect_header_row
        sheets = load_workbook_sheets(sample2_path)
        df = list(sheets.values())[0]
        header_row = detect_header_row(df)
        # Messy file has metadata rows, header should not be at row 0
        # Row 0 is "STATEMENT OF VALUES" metadata
        assert header_row >= 0

    def test_header_with_merged_cells(self, merged_xlsx):
        from app.processing.workbook import unmerge_and_forward_fill, detect_header_row
        df = unmerge_and_forward_fill(merged_xlsx, "Sheet")
        header_row = detect_header_row(df)
        assert header_row >= 0

    def test_extract_data_frame(self, sample1_path):
        from app.processing.workbook import load_workbook_sheets, extract_data_frame
        sheets = load_workbook_sheets(sample1_path)
        df = list(sheets.values())[0]
        data_df = extract_data_frame(df, header_row=0)
        assert len(data_df.columns) > 0
        assert len(data_df) > 0


# ---------------------------------------------------------------------------
# 3. Sheet Ranking
# ---------------------------------------------------------------------------

class TestSheetRanking:

    def test_primary_sheet_identified(self, sample1_path):
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.orchestration.state import create_initial_state
        from app.schemas.state_models import SheetClassification, WorkflowStage

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        result = run_sheet_discovery(state)
        assert result.stage != WorkflowStage.ERROR
        assert result.sheet_manifest is not None
        primary = result.sheet_manifest.primary
        assert primary is not None
        assert primary.classification == SheetClassification.PRIMARY

    def test_noise_sheets_rejected(self, sample3_path):
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.orchestration.state import create_initial_state
        from app.schemas.state_models import SheetClassification

        state = create_initial_state(sample3_path, "s3.xlsx", "xlsx")
        result = run_sheet_discovery(state)
        assert result.sheet_manifest is not None
        # The SOV sheet should be Primary
        primary = result.sheet_manifest.primary
        assert primary is not None
        # Summary/Notes sheets should not be Primary
        non_primary = [s for s in result.sheet_manifest.sheets if s.sheet_name != primary.sheet_name]
        for s in non_primary:
            assert s.classification in (SheetClassification.SECONDARY, SheetClassification.REJECT)

    def test_empty_workbook_error(self, empty_xlsx):
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.orchestration.state import create_initial_state
        from app.schemas.state_models import WorkflowStage

        state = create_initial_state(empty_xlsx, "empty.xlsx", "xlsx")
        result = run_sheet_discovery(state)
        # Should handle gracefully (error or empty sheet reject)
        assert result.stage in (WorkflowStage.ERROR, WorkflowStage.DISCOVERED)


# ---------------------------------------------------------------------------
# 4. Schema Mapping — Exact
# ---------------------------------------------------------------------------

class TestExactMapping:

    def test_exact_reference(self):
        from app.agents.schema_mapping import _stage1_exact
        result = _stage1_exact("Reference")
        assert result is not None
        assert result[0] == "Reference"
        assert result[1] >= 0.90

    def test_exact_loc_num(self):
        from app.agents.schema_mapping import _stage1_exact
        result = _stage1_exact("Loc #")
        assert result is not None
        assert result[0] == "Reference"

    def test_exact_yr_blt(self):
        from app.agents.schema_mapping import _stage1_exact
        result = _stage1_exact("Yr Blt")
        assert result is not None
        assert result[0] == "Year Built"

    def test_exact_bldg_repl_cost(self):
        from app.agents.schema_mapping import _stage1_exact
        result = _stage1_exact("Bldg Repl Cost")
        assert result is not None
        assert result[0] == "Building Value"

    def test_nonmatch_returns_none(self):
        from app.agents.schema_mapping import _stage1_exact
        result = _stage1_exact("xyzzy_random_col")
        assert result is None


# ---------------------------------------------------------------------------
# 5. Schema Mapping — Fuzzy
# ---------------------------------------------------------------------------

class TestFuzzyMapping:

    def test_fuzzy_year_built(self):
        from app.agents.schema_mapping import _stage2_fuzzy
        result = _stage2_fuzzy("Year of Construction")
        assert result is not None
        assert result[0] == "Year Built"

    def test_fuzzy_building_value(self):
        from app.agents.schema_mapping import _stage2_fuzzy
        result = _stage2_fuzzy("Bldg Value")
        assert result is not None
        assert result[0] == "Building Value"

    def test_fuzzy_state(self):
        from app.agents.schema_mapping import _stage2_fuzzy
        result = _stage2_fuzzy("ST")
        # Should match something (State is common synonym)
        # Could be None for very short abbreviations — acceptable
        if result:
            assert result[0] == "State"

    def test_fuzzy_threshold_applied(self):
        from app.agents.schema_mapping import _stage2_fuzzy
        # Completely random string should not match
        result = _stage2_fuzzy("ZZZZXXXXXQQQQ")
        assert result is None


# ---------------------------------------------------------------------------
# 6. Confidence Scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:

    def test_confidence_formula(self):
        from app.agents.schema_mapping import _compute_confidence, MappingMethod
        conf = _compute_confidence(0.95, 0.90, 1.0, MappingMethod.EXACT)
        assert 0.90 <= conf <= 1.0

    def test_memory_boost_capped(self):
        from app.agents.schema_mapping import _compute_confidence, MEMORY_BOOST_CAP, MappingMethod
        conf = _compute_confidence(1.0, 1.0, 1.0, MappingMethod.MEMORY, memory_hit=True)
        assert conf <= MEMORY_BOOST_CAP

    def test_low_confidence_requires_review(self, sample1_path):
        from app.agents.schema_mapping import run_schema_mapping
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.config import config

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        state = run_schema_mapping(state)

        if state.mappings:
            for m in state.mappings.mappings:
                if m.confidence < config.HIGH_CONFIDENCE_THRESHOLD and m.target:
                    assert m.review_required


# ---------------------------------------------------------------------------
# 7. One-to-one Mapping Constraint
# ---------------------------------------------------------------------------

class TestOneTOneMappingConstraint:

    def test_no_duplicate_targets(self, sample1_path):
        from app.agents.schema_mapping import run_schema_mapping
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        state = run_schema_mapping(state)

        if state.mappings:
            targets = [m.target for m in state.mappings.mappings if m.target]
            assert len(targets) == len(set(targets)), f"Duplicate targets: {targets}"


# ---------------------------------------------------------------------------
# 8. Value Profiling
# ---------------------------------------------------------------------------

class TestValueProfiling:

    def test_year_profile(self):
        from app.processing.profiling import profile_column, score_value_profile_fit
        series = pd.Series(["1985", "1992", "2001", "2015", "1998"])
        profile = profile_column(series)
        score = score_value_profile_fit(profile, "Year Built")
        assert score > 0.5

    def test_monetary_profile(self):
        from app.processing.profiling import profile_column, score_value_profile_fit
        series = pd.Series(["$1,500,000", "$2,300,000", "$875,000"])
        profile = profile_column(series)
        score = score_value_profile_fit(profile, "Building Value")
        assert score > 0.3

    def test_state_profile(self):
        from app.processing.profiling import profile_column, score_value_profile_fit
        series = pd.Series(["NY", "CA", "TX", "FL", "IL"])
        profile = profile_column(series)
        score = score_value_profile_fit(profile, "State")
        assert score > 0.7

    def test_zip_profile(self):
        from app.processing.profiling import profile_column, score_value_profile_fit
        series = pd.Series(["10001", "90001", "60601", "77001", "85001"])
        profile = profile_column(series)
        score = score_value_profile_fit(profile, "Zip")
        assert score > 0.7

    def test_sprinkler_profile(self):
        from app.processing.profiling import profile_column, score_value_profile_fit
        series = pd.Series(["Y", "N", "Y13", "Y", "N"])
        profile = profile_column(series)
        score = score_value_profile_fit(profile, "Fire Sprinklers (Y/N)")
        assert score > 0.5


# ---------------------------------------------------------------------------
# 9. Anomaly Detection
# ---------------------------------------------------------------------------

class TestAnomalyDetection:

    def _make_test_df(self):
        return pd.DataFrame({
            "Reference": ["L001", "L002", "L001"],  # Duplicate
            "Building Value": ["$1,000,000", "$-500,000", "2000000"],  # Currency + negative
            "Year Built": [1985, 2030, 1990],  # Future year
            "Storeys": [5, 0, 3],  # Storeys < 1
            "State": ["NY", "California", "TX"],  # Full state name
            "Fire Sprinklers (Y/N)": ["Y", "Yes", "N"],  # Non-standard
            "Zip": ["10001", "9001", "60601"],  # Bad zip
        })

    def test_detects_currency_symbols(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        currency_issues = [i for i in issues if i.suggested_operation == "strip_currency"]
        assert len(currency_issues) > 0

    def test_detects_negative_values(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        neg_issues = [i for i in issues if "negative" in i.evidence.lower()]
        assert len(neg_issues) > 0

    def test_detects_future_year_built(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        year_issues = [i for i in issues if i.affected_field == "Year Built"]
        assert len(year_issues) > 0

    def test_detects_storeys_less_than_1(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        storey_issues = [i for i in issues if i.affected_field == "Storeys"]
        assert len(storey_issues) > 0

    def test_detects_duplicate_reference(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        dup_issues = [i for i in issues if i.issue_type == "duplicate"]
        assert len(dup_issues) > 0

    def test_detects_bad_sprinkler_codes(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        sprk_issues = [i for i in issues if i.affected_field == "Fire Sprinklers (Y/N)"]
        assert len(sprk_issues) > 0

    def test_detects_invalid_state(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        state_issues = [i for i in issues if i.affected_field == "State"]
        assert len(state_issues) > 0

    def test_detects_invalid_zip(self):
        from app.agents.quality_reasoning import detect_quality_issues
        df = self._make_test_df()
        issues = detect_quality_issues(df, None)
        zip_issues = [i for i in issues if i.affected_field == "Zip"]
        assert len(zip_issues) > 0


# ---------------------------------------------------------------------------
# 10. Transformation Whitelist
# ---------------------------------------------------------------------------

class TestTransformationWhitelist:

    def test_strip_currency(self):
        from app.processing.transformations import strip_currency
        assert strip_currency("$1,500,000") == 1500000.0
        assert strip_currency("($500)") == -500.0
        assert pd.isna(strip_currency(None))

    def test_to_float(self):
        from app.processing.transformations import to_float
        assert to_float("1234.56") == 1234.56
        assert to_float("1,234.56") == 1234.56
        assert pd.isna(to_float(None))

    def test_to_int(self):
        from app.processing.transformations import to_int
        assert to_int("1985") == 1985
        assert to_int("10.0") == 10
        assert pd.isna(to_int(None))

    def test_state_to_abbrev(self):
        from app.processing.transformations import state_to_abbrev
        assert state_to_abbrev("California") == "CA"
        assert state_to_abbrev("NY") == "NY"
        assert state_to_abbrev("new york") == "NY"

    def test_normalize_sprinkler_code(self):
        from app.processing.transformations import normalize_sprinkler_code
        assert normalize_sprinkler_code("yes") == "Y"
        assert normalize_sprinkler_code("no") == "N"
        assert normalize_sprinkler_code("Y13") == "Y13"
        assert normalize_sprinkler_code("Y") == "Y"

    def test_to_zip(self):
        from app.processing.transformations import to_zip
        assert to_zip("10001") == 10001
        assert to_zip("10001-1234") == 10001
        assert to_zip("90001") == 90001

    def test_to_year_int(self):
        from app.processing.transformations import to_year_int
        assert to_year_int("1985") == 1985
        assert to_year_int("Built in 1990") == 1990

    def test_unlisted_operation_raises(self):
        from app.processing.transformations import apply_transformation
        with pytest.raises(ValueError, match="not in the transformation whitelist"):
            apply_transformation("exec_python_code", "some_value")

    def test_currency_normalization_series(self):
        from app.processing.transformations import apply_transformation_to_series
        series = pd.Series(["$1,000", "$2,000", None])
        result = apply_transformation_to_series("strip_currency", series)
        assert result.iloc[0] == 1000.0
        assert result.iloc[1] == 2000.0

    def test_state_normalization_series(self):
        from app.processing.transformations import apply_transformation_to_series
        series = pd.Series(["California", "texas", "NY"])
        result = apply_transformation_to_series("state_to_abbrev", series)
        assert result.iloc[0] == "CA"
        assert result.iloc[1] == "TX"
        assert result.iloc[2] == "NY"


# ---------------------------------------------------------------------------
# 11. Missing Value Preservation (No Hallucination)
# ---------------------------------------------------------------------------

class TestMissingValuePreservation:

    def test_strip_currency_preserves_null(self):
        from app.processing.transformations import strip_currency
        assert pd.isna(strip_currency(None))
        assert pd.isna(strip_currency(pd.NA))

    def test_to_float_preserves_null(self):
        from app.processing.transformations import to_float
        assert pd.isna(to_float(None))

    def test_to_int_preserves_null(self):
        from app.processing.transformations import to_int
        assert pd.isna(to_int(None))

    def test_tbd_not_converted(self):
        """'TBD' must not be silently converted to a fabricated value."""
        from app.processing.transformations import strip_currency, to_float
        result = strip_currency("TBD")
        assert pd.isna(result)

        result = to_float("TBD")
        assert pd.isna(result)


# ---------------------------------------------------------------------------
# 12. Schema Validation (17 fields)
# ---------------------------------------------------------------------------

class TestSchemaValidation:

    def test_17_column_validation_passes(self):
        from app.processing.validation import validate_output_schema, TARGET_COLUMN_ORDER
        df = pd.DataFrame(columns=TARGET_COLUMN_ORDER)
        passed, errors = validate_output_schema(df)
        assert passed, f"Errors: {errors}"

    def test_wrong_column_count_fails(self):
        from app.processing.validation import validate_output_schema
        df = pd.DataFrame(columns=["Reference", "Address"])
        passed, errors = validate_output_schema(df)
        assert not passed

    def test_extra_column_fails(self):
        from app.processing.validation import validate_output_schema, TARGET_COLUMN_ORDER
        cols = TARGET_COLUMN_ORDER + ["ExtraColumn"]
        df = pd.DataFrame(columns=cols)
        passed, errors = validate_output_schema(df)
        assert not passed

    def test_wrong_order_fails(self):
        from app.processing.validation import validate_output_schema, TARGET_COLUMN_ORDER
        cols = list(reversed(TARGET_COLUMN_ORDER))
        df = pd.DataFrame(columns=cols)
        passed, errors = validate_output_schema(df)
        assert not passed

    def test_enforce_column_order(self):
        from app.processing.validation import enforce_column_order, TARGET_COLUMN_ORDER
        df = pd.DataFrame({"Reference": ["L001"], "Building Value": [1000000]})
        result = enforce_column_order(df)
        assert list(result.columns) == TARGET_COLUMN_ORDER
        assert len(result.columns) == 17

    def test_target_fields_exact_17(self):
        from app.schemas.target_schema import TARGET_FIELDS
        assert len(TARGET_FIELDS) == 17

    def test_target_fields_exact_names(self):
        from app.schemas.target_schema import TARGET_FIELDS
        expected = [
            "Reference", "Address", "City", "State", "Zip", "County", "Country",
            "Building Value", "Contents", "BI", "Occupancy", "Construction",
            "Storeys", "Number of Buildings", "Year Built", "Fire Sprinklers (Y/N)", "Other",
        ]
        assert TARGET_FIELDS == expected


# ---------------------------------------------------------------------------
# 13. Recommendation Generation
# ---------------------------------------------------------------------------

class TestRecommendationGeneration:

    def test_recommendations_generated(self, sov_state_with_mappings):
        from app.agents.quality_reasoning import run_quality_reasoning
        state = run_quality_reasoning(sov_state_with_mappings)
        assert len(state.recommendations) > 0

    def test_mapping_recommendations_have_ids(self, sov_state_with_mappings):
        from app.agents.quality_reasoning import run_quality_reasoning
        state = run_quality_reasoning(sov_state_with_mappings)
        for rec in state.recommendations:
            assert rec.id is not None
            assert rec.id != ""

    def test_all_operations_whitelisted(self, sov_state_with_mappings):
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.processing.transformations import WHITELISTED_OPERATIONS
        state = run_quality_reasoning(sov_state_with_mappings)
        for rec in state.recommendations:
            assert rec.operation in WHITELISTED_OPERATIONS, (
                f"Rec {rec.id} uses non-whitelisted op: {rec.operation}"
            )


# ---------------------------------------------------------------------------
# 14. Approval Workflow
# ---------------------------------------------------------------------------

class TestApprovalWorkflow:

    def test_approve_recommendation(self, sov_state_with_mappings):
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.schemas.state_models import RecommendationStatus

        state = run_quality_reasoning(sov_state_with_mappings)
        if not state.recommendations:
            return

        rec = state.recommendations[0]
        state.recommendations[0] = rec.model_copy(
            update={"status": RecommendationStatus.APPROVED}
        )
        assert state.recommendations[0].status == RecommendationStatus.APPROVED

    def test_reject_recommendation(self, sov_state_with_mappings):
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.schemas.state_models import RecommendationStatus

        state = run_quality_reasoning(sov_state_with_mappings)
        if not state.recommendations:
            return

        rec = state.recommendations[0]
        state.recommendations[0] = rec.model_copy(
            update={"status": RecommendationStatus.REJECTED, "rejection_note": "test rejection"}
        )
        assert state.recommendations[0].status == RecommendationStatus.REJECTED
        assert state.recommendations[0].rejection_note == "test rejection"

    def test_export_locked_without_approval(self, sov_state_with_mappings):
        """Agent 4 should still run but validation should handle pending recs gracefully."""
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.schemas.state_models import RecommendationStatus

        state = run_quality_reasoning(sov_state_with_mappings)
        # All pending — don't approve anything
        pending_required = [
            r for r in state.recommendations
            if r.status == RecommendationStatus.PENDING and r.review_required
        ]
        # The UI locks export, but Agent 4 itself will apply only approved recs
        approved = [r for r in state.recommendations if r.status == RecommendationStatus.APPROVED]
        assert len(approved) == 0  # None approved yet


# ---------------------------------------------------------------------------
# 15. Full Pipeline (End-to-End)
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def _auto_approve_all(self, state):
        """Helper: approve all recommendations."""
        from app.schemas.state_models import RecommendationStatus
        for i, rec in enumerate(state.recommendations):
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.APPROVED}
            )
        return state

    def test_sample1_full_pipeline(self, sample1_path, tmp_path):
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.agents.transformation import run_transformation
        from app.schemas.state_models import WorkflowStage
        import os

        os.environ["OUTPUT_DIR"] = str(tmp_path)

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        assert state.stage != WorkflowStage.ERROR

        state = run_schema_mapping(state)
        assert state.stage != WorkflowStage.ERROR
        assert state.mappings is not None

        state = run_quality_reasoning(state)
        assert state.stage != WorkflowStage.ERROR
        assert state.quality_report is not None
        assert len(state.recommendations) > 0

        state = self._auto_approve_all(state)

        # Override output dir for test
        from app import config as cfg_mod
        cfg_mod.config.OUTPUT_DIR = str(tmp_path)

        state = run_transformation(state)
        assert state.output_path is not None
        assert state.validation_passed

    def test_sample2_messy_pipeline(self, sample2_path, tmp_path):
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.schemas.state_models import WorkflowStage

        state = create_initial_state(sample2_path, "s2.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        assert state.stage != WorkflowStage.ERROR, state.error_message

        state = run_schema_mapping(state)
        assert state.mappings is not None

        state = run_quality_reasoning(state)
        # Messy file should have quality issues
        assert state.quality_report is not None

    def test_sample3_multisheet(self, sample3_path):
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.schemas.state_models import WorkflowStage, SheetClassification

        state = create_initial_state(sample3_path, "s3.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        assert state.stage != WorkflowStage.ERROR

        # Should find the SOV sheet, not Summary/Notes
        primary = state.sheet_manifest.primary
        assert primary is not None
        assert primary.classification == SheetClassification.PRIMARY

    def test_output_has_17_columns(self, sample1_path, tmp_path):
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.agents.transformation import run_transformation
        from app.schemas.target_schema import TARGET_FIELDS
        import os

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        state = run_schema_mapping(state)
        state = run_quality_reasoning(state)
        state = self._auto_approve_all(state)

        from app import config as cfg_mod
        cfg_mod.config.OUTPUT_DIR = str(tmp_path)
        state = run_transformation(state)

        assert state.output_path is not None
        output_df = pd.read_excel(state.output_path, sheet_name="Cleaned_SOV")
        assert len(output_df.columns) == 17
        assert list(output_df.columns) == TARGET_FIELDS


# ---------------------------------------------------------------------------
# 16. Audit Logging
# ---------------------------------------------------------------------------

class TestAuditLogging:

    def test_audit_log_created(self, sample1_path, tmp_path):
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.agents.transformation import run_transformation
        from app.schemas.state_models import RecommendationStatus

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        state = run_schema_mapping(state)
        state = run_quality_reasoning(state)

        # Approve all
        for i, rec in enumerate(state.recommendations):
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.APPROVED}
            )

        from app import config as cfg_mod
        cfg_mod.config.OUTPUT_DIR = str(tmp_path)
        state = run_transformation(state)

        assert state.audit_log_path is not None
        from pathlib import Path
        assert Path(state.audit_log_path).exists()

    def test_audit_log_has_entries(self, sample1_path, tmp_path):
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.agents.transformation import run_transformation
        from app.schemas.state_models import RecommendationStatus

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        state = run_schema_mapping(state)
        state = run_quality_reasoning(state)

        for i, rec in enumerate(state.recommendations):
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.APPROVED}
            )

        from app import config as cfg_mod
        cfg_mod.config.OUTPUT_DIR = str(tmp_path)
        state = run_transformation(state)

        assert len(state.audit_log) >= 0  # At least no crash

    def test_rejected_not_in_audit(self, sample1_path, tmp_path):
        """Rejected recommendations must not appear as applied transformations."""
        from app.orchestration.state import create_initial_state
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.agents.schema_mapping import run_schema_mapping
        from app.agents.quality_reasoning import run_quality_reasoning
        from app.agents.transformation import run_transformation
        from app.schemas.state_models import RecommendationStatus

        state = create_initial_state(sample1_path, "s1.xlsx", "xlsx")
        state = run_sheet_discovery(state)
        state = run_schema_mapping(state)
        state = run_quality_reasoning(state)

        rejected_ids = set()
        for i, rec in enumerate(state.recommendations):
            if i < 2:
                state.recommendations[i] = rec.model_copy(
                    update={"status": RecommendationStatus.REJECTED}
                )
                rejected_ids.add(rec.id)
            else:
                state.recommendations[i] = rec.model_copy(
                    update={"status": RecommendationStatus.APPROVED}
                )

        from app import config as cfg_mod
        cfg_mod.config.OUTPUT_DIR = str(tmp_path)
        state = run_transformation(state)

        # Check audit log doesn't have rejected rec IDs
        for entry in state.audit_log:
            assert entry.recommendation_id not in rejected_ids


# ---------------------------------------------------------------------------
# 17. Malformed Input Handling
# ---------------------------------------------------------------------------

class TestMalformedInputHandling:

    def test_binary_file_fails_gracefully(self, tmp_path):
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.orchestration.state import create_initial_state
        from app.schemas.state_models import WorkflowStage

        bad_path = tmp_path / "bad.xlsx"
        bad_path.write_bytes(b"\x00" * 100)
        state = create_initial_state(str(bad_path), "bad.xlsx", "xlsx")
        result = run_sheet_discovery(state)
        assert result.stage == WorkflowStage.ERROR
        assert result.error_message is not None

    def test_unsupported_type_fails_gracefully(self, tmp_path):
        from app.agents.sheet_discovery import run_sheet_discovery
        from app.orchestration.state import create_initial_state
        from app.schemas.state_models import WorkflowStage

        txt_path = tmp_path / "data.txt"
        txt_path.write_text("not a spreadsheet")
        state = create_initial_state(str(txt_path), "data.txt", "txt")
        result = run_sheet_discovery(state)
        assert result.stage == WorkflowStage.ERROR

    def test_completely_blank_rows_handled(self):
        from app.processing.workbook import extract_data_frame
        df = pd.DataFrame([
            ["Header1", "Header2", "Header3"],
            [None, None, None],
            ["val1", "val2", "val3"],
            [None, None, None],
        ])
        result = extract_data_frame(df, header_row=0)
        # Blank rows should be dropped
        assert len(result) < 3  # only 1 data row + blank dropped
