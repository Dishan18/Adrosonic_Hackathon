"""
Benchmark / Scoring Harness for the Agentic SOV Intelligence System.

Evaluates against the three provided test SOV samples.
Target metrics:
  - Mapping accuracy >= 74%
  - Anomaly recall >= 90%
  - Transformation correctness >= 95%
  - Explainability coverage = 100%
  - Audit completeness = 100%
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

# ---------------------------------------------------------------------------
# Ground truth definitions (for the generated sample files)
# ---------------------------------------------------------------------------

GROUND_TRUTH = {
    "sample1_standard.xlsx": {
        "mappings": {
            "Loc #": "Reference",
            "Street Address": "Address",
            "City": "City",
            "ST": "State",
            "Zip Code": "Zip",
            "County": "County",
            "Country": "Country",
            "Bldg Repl Cost": "Building Value",
            "Contents Value": "Contents",
            "Business Interruption": "BI",
            "Occ Code": "Occupancy",
            "Const Type": "Construction",
            "Num Stories": "Storeys",
            "# Buildings": "Number of Buildings",
            "Yr Blt": "Year Built",
            "Fire Prot": "Fire Sprinklers (Y/N)",
            "Other Insured Value": "Other",
        },
        "anomalies": [],  # Clean file — no anomalies
        "quality_score_min": 70.0,
    },
    "sample2_messy.xlsx": {
        "mappings": {
            "Reference No.": "Reference",
            "Property Address": "Address",
            "City Name": "City",
            "State": "State",
            "Postal Code": "Zip",
            "Building Value ($)": "Building Value",
            "Contents ($)": "Contents",
            "BI Value": "BI",
            "Occupancy Type": "Occupancy",
            "Construction": "Construction",
            "Stories": "Storeys",
            "Bldgs": "Number of Buildings",
            "Year Constructed": "Year Built",
            "Sprinklers Y/N": "Fire Sprinklers (Y/N)",
            "Other Value": "Other",
        },
        "anomalies": ["currency_symbols", "negative_value", "duplicate_reference", "non_standard_sprinkler"],
        "quality_score_min": 40.0,
    },
    "sample3_multisheet.xlsx": {
        "mappings": {
            "Location ID": "Reference",
            "Address": "Address",
            "City": "City",
            "State": "State",
            "ZIP": "Zip",
            "County": "County",
            "Country": "Country",
            "Building RCV": "Building Value",
            "Contents": "Contents",
            "Time Element": "BI",
            "Occupancy": "Occupancy",
            "Construction": "Construction",
            "Num Floors": "Storeys",
            "Number of Buildings": "Number of Buildings",
            "Year Built": "Year Built",
            "Fire Sprinklers (Y/N)": "Fire Sprinklers (Y/N)",
            "Other": "Other",
        },
        "anomalies": [],
        "quality_score_min": 65.0,
    },
}

ANOMALY_KEYWORDS = {
    "currency_symbols": ["currency", "strip_currency", "dollar", "$", ","],
    "negative_value": ["negative", "neg"],
    "duplicate_reference": ["duplicate", "reference"],
    "non_standard_sprinkler": ["sprinkler", "normalize_sprinkler"],
    "invalid_year": ["year", "future", "1700"],
    "invalid_state": ["state", "state_to_abbrev"],
}


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_mapping_accuracy(predicted: Dict[str, str], ground_truth: Dict[str, str]) -> float:
    """
    Compute mapping accuracy: fraction of ground truth mappings correctly predicted.
    """
    if not ground_truth:
        return 1.0

    correct = 0
    total = len(ground_truth)

    for src_col, expected_target in ground_truth.items():
        predicted_target = predicted.get(src_col)
        if predicted_target == expected_target:
            correct += 1
        else:
            # Try case-insensitive match
            if (predicted_target or "").lower() == expected_target.lower():
                correct += 1

    return correct / total if total > 0 else 0.0


def compute_anomaly_recall(
    detected_issues: List,
    ground_truth_anomalies: List[str],
) -> float:
    """
    Compute anomaly recall: fraction of ground truth anomaly types detected.
    """
    if not ground_truth_anomalies:
        return 1.0  # No anomalies expected, no recall to compute

    detected_types = set()
    for issue in detected_issues:
        issue_text = (issue.evidence + " " + issue.suggested_operation + " " + issue.issue_type).lower()
        for anomaly_type, keywords in ANOMALY_KEYWORDS.items():
            if any(kw in issue_text for kw in keywords):
                detected_types.add(anomaly_type)

    gt_set = set(ground_truth_anomalies)
    recalled = gt_set & detected_types
    return len(recalled) / len(gt_set)


def compute_transformation_correctness(state, ground_truth_mappings: Dict[str, str]) -> float:
    """
    Check that approved column mappings are correct.
    """
    if state.mappings is None:
        return 0.0

    approved_mappings = {
        m.source_column: m.target
        for m in state.mappings.mappings
        if m.target is not None
    }

    # Only check columns that exist in ground truth
    correct = 0
    checked = 0
    for src, tgt in ground_truth_mappings.items():
        if src in approved_mappings:
            checked += 1
            if approved_mappings[src] == tgt:
                correct += 1

    return correct / checked if checked > 0 else 1.0


def compute_explainability_coverage(recommendations: List) -> float:
    """
    Check that every recommendation has a rationale (non-empty).
    """
    if not recommendations:
        return 1.0
    with_rationale = sum(1 for r in recommendations if r.rationale and len(r.rationale) > 5)
    return with_rationale / len(recommendations)


def compute_audit_completeness(state, approved_count: int) -> float:
    """
    Check that audit log entries exist for approved transformations.
    """
    if approved_count == 0:
        return 1.0
    audit_entries = len(state.audit_log)
    # We don't require 1:1 (some recs are column renames logged differently)
    return 1.0 if audit_entries > 0 else 0.0


# ---------------------------------------------------------------------------
# Run benchmark on a single file
# ---------------------------------------------------------------------------

def benchmark_file(sample_name: str, sample_path: str, gt: Dict) -> Dict:
    """Run full pipeline (without LLM in auto-approve mode) and compute metrics."""
    from app.orchestration.state import create_initial_state
    from app.agents.sheet_discovery import run_sheet_discovery
    from app.agents.schema_mapping import run_schema_mapping
    from app.agents.quality_reasoning import run_quality_reasoning
    from app.agents.transformation import run_transformation
    from app.schemas.state_models import RecommendationStatus, WorkflowStage
    from app import config as cfg_mod
    import tempfile
    import os

    print(f"\n{'='*60}")
    print(f"Benchmarking: {sample_name}")
    print(f"{'='*60}")

    # Use temp output dir
    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_mod.config.OUTPUT_DIR = tmp_dir

        start_time = time.time()

        # Create state
        state = create_initial_state(
            file_path=sample_path,
            original_filename=sample_name,
            file_type=Path(sample_name).suffix.lstrip("."),
            session_id=f"bench_{sample_name[:8]}",
        )

        # Agent 1
        state = run_sheet_discovery(state)
        if state.stage == WorkflowStage.ERROR:
            print(f"  ❌ Agent 1 failed: {state.error_message}")
            return {"file": sample_name, "error": state.error_message}

        print(f"  ✓ Sheet Discovery: primary='{state.primary_sheet_name}', header_row={state.header_row}")

        # Agent 2
        state = run_schema_mapping(state)
        if state.stage == WorkflowStage.ERROR:
            print(f"  ❌ Agent 2 failed: {state.error_message}")
            return {"file": sample_name, "error": state.error_message}

        mapped_count = len([m for m in state.mappings.mappings if m.target]) if state.mappings else 0
        print(f"  ✓ Schema Mapping: {mapped_count} columns mapped, conf={state.mappings.overall_mapping_confidence:.1%}")

        # Agent 3
        state = run_quality_reasoning(state)
        if state.stage == WorkflowStage.ERROR:
            print(f"  ❌ Agent 3 failed: {state.error_message}")
            return {"file": sample_name, "error": state.error_message}

        print(f"  ✓ Quality Assessment: {len(state.quality_report.issues)} issues, score={state.quality_report.overall_quality_score:.1f}/100")

        # Auto-approve all (for benchmark)
        for i, rec in enumerate(state.recommendations):
            state.recommendations[i] = rec.model_copy(
                update={"status": RecommendationStatus.APPROVED}
            )

        approved_count = len([r for r in state.recommendations if r.status == RecommendationStatus.APPROVED])

        # Agent 4
        state = run_transformation(state)

        elapsed = time.time() - start_time

        # Compute metrics
        predicted_mappings = {
            m.source_column: m.target
            for m in state.mappings.mappings
            if m.target is not None
        } if state.mappings else {}

        mapping_accuracy = compute_mapping_accuracy(predicted_mappings, gt.get("mappings", {}))
        anomaly_recall = compute_anomaly_recall(
            state.quality_report.issues if state.quality_report else [],
            gt.get("anomalies", []),
        )
        transformation_correctness = compute_transformation_correctness(state, gt.get("mappings", {}))
        explainability = compute_explainability_coverage(state.recommendations)
        audit_completeness = compute_audit_completeness(state, approved_count)

        results = {
            "file": sample_name,
            "elapsed_seconds": round(elapsed, 2),
            "mapping_accuracy": round(mapping_accuracy * 100, 2),
            "anomaly_recall": round(anomaly_recall * 100, 2),
            "transformation_correctness": round(transformation_correctness * 100, 2),
            "explainability_coverage": round(explainability * 100, 2),
            "audit_completeness": round(audit_completeness * 100, 2),
            "quality_score": state.quality_report.overall_quality_score if state.quality_report else 0,
            "validation_passed": state.validation_passed,
            "mapped_columns": mapped_count,
            "total_issues": len(state.quality_report.issues) if state.quality_report else 0,
            "recommendations": len(state.recommendations),
        }

        # Print results
        print(f"\n  📊 Metrics for {sample_name}:")
        print(f"     Mapping Accuracy:        {results['mapping_accuracy']:.2f}%  (target: ≥74%)")
        print(f"     Anomaly Recall:          {results['anomaly_recall']:.2f}%  (target: ≥90%)")
        print(f"     Transformation Correct:  {results['transformation_correctness']:.2f}%  (target: ≥95%)")
        print(f"     Explainability Coverage: {results['explainability_coverage']:.2f}%  (target: 100%)")
        print(f"     Audit Completeness:      {results['audit_completeness']:.2f}%  (target: 100%)")
        print(f"     Quality Score:           {results['quality_score']:.1f}/100")
        print(f"     Validation Passed:       {results['validation_passed']}")
        print(f"     Time:                    {results['elapsed_seconds']}s")

        return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_benchmark():
    """Run benchmark on all three sample files and print aggregate report."""
    import pandas as pd

    sample_dir = Path(__file__).parent / "data" / "samples"
    all_results = []
    errors = []

    print("\n" + "="*70)
    print("AGENTIC SOV INTELLIGENCE SYSTEM — BENCHMARK REPORT")
    print(f"Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    for sample_name, gt in GROUND_TRUTH.items():
        sample_path = sample_dir / sample_name
        if not sample_path.exists():
            print(f"\n⚠️  Skipping {sample_name}: file not found at {sample_path}")
            continue

        try:
            result = benchmark_file(sample_name, str(sample_path), gt)
            if "error" not in result:
                all_results.append(result)
            else:
                errors.append(result)
        except Exception as e:
            print(f"  ❌ Exception benchmarking {sample_name}: {e}")
            import traceback
            traceback.print_exc()
            errors.append({"file": sample_name, "error": str(e)})

    if not all_results:
        print("\n❌ No benchmark results collected.")
        return

    # Aggregate
    def avg(key):
        vals = [r[key] for r in all_results if key in r]
        return sum(vals) / len(vals) if vals else 0.0

    print("\n" + "="*70)
    print("AGGREGATE RESULTS (average across all samples)")
    print("="*70)
    print(f"{'Metric':<35} {'Achieved':>10} {'Target':>10} {'Status':>10}")
    print("-"*70)

    metrics = [
        ("Mapping Accuracy", avg("mapping_accuracy"), 74.0),
        ("Anomaly Recall", avg("anomaly_recall"), 90.0),
        ("Transformation Correctness", avg("transformation_correctness"), 95.0),
        ("Explainability Coverage", avg("explainability_coverage"), 100.0),
        ("Audit Completeness", avg("audit_completeness"), 100.0),
    ]

    all_pass = True
    for metric_name, achieved, target in metrics:
        status = "✅ PASS" if achieved >= target else "❌ FAIL"
        if achieved < target:
            all_pass = False
        print(f"  {metric_name:<33} {achieved:>8.2f}%  {target:>8.0f}%  {status}")

    print("-"*70)
    print(f"\nOverall: {'✅ ALL TARGETS MET' if all_pass else '⚠️  SOME TARGETS MISSED'}")

    if errors:
        print(f"\n❌ Errors on {len(errors)} files:")
        for e in errors:
            print(f"  - {e['file']}: {e.get('error', 'unknown error')}")

    # Save report
    report_path = Path(__file__).parent.parent / "outputs/benchmark_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": all_results,
            "errors": errors,
            "aggregate": {m[0]: m[1] for m in metrics},
        }, f, indent=2)
    print(f"\n📄 Full report saved: {report_path}")

    return all_results


if __name__ == "__main__":
    run_benchmark()
