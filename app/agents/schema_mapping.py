"""
Agent 2: Schema Mapping Agent.

Cascade mapping pipeline:
  Stage 0: Vector memory (ChromaDB) — previously approved mappings
  Stage 1: Exact normalized match
  Stage 2: Fuzzy matching (RapidFuzz)
  Stage 3: Semantic similarity (sentence-transformers)
  Stage 4: LLM reasoning (for genuinely ambiguous cases)

Uses value-profile cross-checking and Hungarian algorithm for 1:1 assignment.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from app.schemas.state_models import (
    ColumnMapping,
    MappingMethod,
    MappingResult,
    SOVState,
    WorkflowStage,
)
from app.schemas.target_schema import (
    TARGET_DEFINITIONS,
    TARGET_FIELDS,
    TARGET_SYNONYMS,
)
from app.processing.workbook import unmerge_and_forward_fill, extract_data_frame
from app.processing.profiling import profile_column, score_value_profile_fit
from app.config import config

logger = logging.getLogger(__name__)

# Confidence weights from PDF2
W_NAME = 0.45
W_VALUE = 0.35
W_METHOD = 0.20

# Memory boost cap
MEMORY_BOOST_CAP = 0.99


# ---------------------------------------------------------------------------
# String normalization
# ---------------------------------------------------------------------------

def normalize(s: str) -> str:
    """Normalize a header string for exact/fuzzy matching."""
    s = str(s).lower().strip()
    s = re.sub(r"[\s_\-\.#\(\)/&]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Build target lookup tables
# ---------------------------------------------------------------------------

def _build_exact_lookup() -> Dict[str, str]:
    """Build normalized string → target field lookup."""
    lookup: Dict[str, str] = {}
    for field in TARGET_FIELDS:
        lookup[normalize(field)] = field
    for field, synonyms in TARGET_SYNONYMS.items():
        for syn in synonyms:
            lookup[normalize(syn)] = field
    return lookup


_EXACT_LOOKUP: Optional[Dict[str, str]] = None


def get_exact_lookup() -> Dict[str, str]:
    global _EXACT_LOOKUP
    if _EXACT_LOOKUP is None:
        _EXACT_LOOKUP = _build_exact_lookup()
    return _EXACT_LOOKUP


def _build_synonym_corpus() -> Tuple[List[str], List[str]]:
    """
    Build a flat list of (text, target_field) for fuzzy/semantic matching.
    Includes field names, definitions, and synonyms.
    """
    texts = []
    targets = []
    for field in TARGET_FIELDS:
        texts.append(field)
        targets.append(field)
        texts.append(TARGET_DEFINITIONS[field])
        targets.append(field)
        for syn in TARGET_SYNONYMS.get(field, []):
            texts.append(syn)
            targets.append(field)
    return texts, targets


_CORPUS_TEXTS: Optional[List[str]] = None
_CORPUS_TARGETS: Optional[List[str]] = None


def get_corpus():
    global _CORPUS_TEXTS, _CORPUS_TARGETS
    if _CORPUS_TEXTS is None:
        _CORPUS_TEXTS, _CORPUS_TARGETS = _build_synonym_corpus()
    return _CORPUS_TEXTS, _CORPUS_TARGETS


# ---------------------------------------------------------------------------
# Stage 0: Memory
# ---------------------------------------------------------------------------

def _stage0_memory(source_col: str) -> Optional[Tuple[str, float, List[str]]]:
    """Returns (target, confidence, evidence) or None."""
    try:
        from app.services.memory.chroma_store import get_exact_memory_mapping
        match = get_exact_memory_mapping(source_col)
        if match:
            evidence = [
                f"Previously approved mapping: '{match['source_column']}' → '{match['target_field']}'",
                f"Similarity: {match['similarity']:.3f}",
                f"Original confidence: {match['confidence']:.3f}",
            ]
            return match["target_field"], min(match["confidence"], MEMORY_BOOST_CAP), evidence
    except Exception as e:
        logger.debug("Memory stage skipped: %s", e)
    return None


# ---------------------------------------------------------------------------
# Stage 1: Exact normalized match
# ---------------------------------------------------------------------------

def _stage1_exact(source_col: str) -> Optional[Tuple[str, float, List[str]]]:
    """Returns (target, confidence, evidence) or None."""
    norm = normalize(source_col)
    lookup = get_exact_lookup()
    if norm in lookup:
        target = lookup[norm]
        return target, 0.97, [f"Exact normalized match: '{norm}' → '{target}'"]
    return None


# ---------------------------------------------------------------------------
# Stage 2: Fuzzy matching
# ---------------------------------------------------------------------------

def _stage2_fuzzy(source_col: str) -> Optional[Tuple[str, float, List[str]]]:
    """Returns (target, confidence, evidence) or None."""
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        logger.warning("RapidFuzz not available — skipping fuzzy stage.")
        return None

    texts, targets = get_corpus()
    norm_src = normalize(source_col)
    norm_texts = [normalize(t) for t in texts]

    # Use token_sort_ratio for flexibility
    result = process.extractOne(
        norm_src,
        norm_texts,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=int(config.FUZZY_THRESHOLD * 100),
    )

    if result:
        match_text, score, idx = result
        target = targets[idx]
        confidence = score / 100.0
        evidence = [
            f"Fuzzy match: '{source_col}' ≈ '{texts[idx]}' (score={score:.1f}%)",
            f"Matched target: '{target}'",
        ]
        return target, confidence * 0.92, evidence  # slight discount for fuzzy

    return None


# ---------------------------------------------------------------------------
# Stage 3: Semantic similarity
# ---------------------------------------------------------------------------

_CORPUS_EMBEDDINGS = None


def _get_corpus_embeddings():
    global _CORPUS_EMBEDDINGS
    if _CORPUS_EMBEDDINGS is not None:
        return _CORPUS_EMBEDDINGS

    try:
        from app.services.embeddings.encoder import embed_texts
        texts, _ = get_corpus()
        embeddings = embed_texts(texts)
        if embeddings is not None:
            _CORPUS_EMBEDDINGS = embeddings
            logger.info("Corpus embeddings built: %d vectors", len(embeddings))
        return _CORPUS_EMBEDDINGS
    except Exception as e:
        logger.warning("Failed to build corpus embeddings: %s", e)
        return None


def _stage3_semantic(source_col: str) -> Optional[Tuple[str, float, List[str]]]:
    """Returns (target, confidence, evidence) or None."""
    try:
        from app.services.embeddings.encoder import embed_texts, batch_similarity
        import numpy as np

        query_emb = embed_texts([source_col])
        if query_emb is None:
            return None

        corpus_emb = _get_corpus_embeddings()
        if corpus_emb is None:
            return None

        texts, targets = get_corpus()
        sims = batch_similarity(query_emb[0], corpus_emb)

        best_idx = int(max(range(len(sims)), key=lambda i: sims[i]))
        best_sim = sims[best_idx]

        if best_sim >= config.SEMANTIC_THRESHOLD:
            target = targets[best_idx]
            evidence = [
                f"Semantic similarity: '{source_col}' ↔ '{texts[best_idx]}' = {best_sim:.3f}",
                f"Matched target: '{target}'",
            ]
            return target, best_sim * 0.90, evidence  # slight discount for semantic

        return None
    except Exception as e:
        logger.warning("Semantic stage failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Stage 4: LLM reasoning
# ---------------------------------------------------------------------------

def _stage4_llm(
    source_col: str,
    sample_values: List[str],
    candidates: List[Tuple[str, float]],
) -> Optional[Tuple[Optional[str], float, List[str]]]:
    """
    Use LLM to resolve genuinely ambiguous mappings.
    Returns (target_or_None, confidence, evidence).
    """
    try:
        from app.services.llm.gateway import get_llm
        from app.schemas.recommendations import MappingDecision

        llm = get_llm()
        if not llm.available:
            return None

        # Build candidate info
        candidates_text = "\n".join(
            f"  - {field}: {TARGET_DEFINITIONS[field]}"
            for field, _ in candidates[:5]
            if field in TARGET_DEFINITIONS
        )

        sample_text = ", ".join(str(v) for v in sample_values[:5])

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a precise data schema mapping assistant for Statement of Values (SOV) insurance data.\n"
                    "Your task: decide which of the 17 target SOV fields a source column maps to, or null if none applies.\n"
                    "Be conservative. Only map with confidence if the evidence is clear.\n"
                    "NEVER invent or fabricate values."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Source column: '{source_col}'\n"
                    f"Sample values (masked/limited): {sample_text}\n\n"
                    f"Candidate target fields:\n{candidates_text}\n\n"
                    f"All valid target fields: {', '.join(TARGET_FIELDS)}\n\n"
                    "Return a JSON object with fields: "
                    "source_column, target_field (one of the valid targets or null), "
                    "confidence (0.0-1.0), rationale (string), requires_review (bool)."
                ),
            },
        ]

        result = llm.complete_structured(messages, MappingDecision)
        if result is None:
            return None

        # Validate target
        if result.target_field is not None and result.target_field not in TARGET_FIELDS:
            logger.warning("LLM returned invalid target '%s'", result.target_field)
            return None, 0.0, [f"LLM returned invalid target: {result.target_field}"]

        evidence = [
            f"LLM reasoning: {result.rationale}",
            f"LLM confidence: {result.confidence:.3f}",
        ]
        return result.target_field, result.confidence * 0.85, evidence  # LLM discount

    except Exception as e:
        logger.warning("LLM mapping stage failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Value-profile scoring
# ---------------------------------------------------------------------------

def _compute_confidence(
    name_similarity: float,
    value_profile_fit: float,
    method_agreement: float,
    method: MappingMethod,
    memory_hit: bool = False,
) -> float:
    score = (
        W_NAME * name_similarity
        + W_VALUE * value_profile_fit
        + W_METHOD * method_agreement
    )
    if memory_hit:
        score = min(MEMORY_BOOST_CAP, score * 1.1)
    return round(min(1.0, max(0.0, score)), 4)


# ---------------------------------------------------------------------------
# Main mapping cascade for one column
# ---------------------------------------------------------------------------

def map_column(
    source_col: str,
    series: pd.Series,
    already_mapped: Set[str],
) -> ColumnMapping:
    """
    Run the full cascade for a single source column.
    Returns a ColumnMapping.
    """
    # Profile values
    value_profile = profile_column(series)

    # Sample values (limited, for LLM)
    sample_values = list(series.dropna().astype(str).head(config.LLM_SAMPLE_ROWS))

    # --- Stage 0: Memory ---
    mem_result = _stage0_memory(source_col)
    if mem_result:
        target, conf, evidence = mem_result
        if target not in already_mapped:
            vpf = score_value_profile_fit(value_profile, target)
            final_conf = _compute_confidence(conf, vpf, 1.0, MappingMethod.MEMORY, memory_hit=True)
            return ColumnMapping(
                source_column=source_col,
                target=target,
                confidence=final_conf,
                method=MappingMethod.MEMORY,
                rationale=f"Retrieved from approved memory: {evidence[0]}",
                evidence=evidence,
                review_required=final_conf < config.HIGH_CONFIDENCE_THRESHOLD,
                value_profile_fit=vpf,
                name_similarity=conf,
                method_agreement=1.0,
            )

    # --- Stage 1: Exact ---
    exact_result = _stage1_exact(source_col)
    if exact_result:
        target, name_sim, evidence = exact_result
        if target not in already_mapped:
            vpf = score_value_profile_fit(value_profile, target)
            final_conf = _compute_confidence(name_sim, vpf, 1.0, MappingMethod.EXACT)
            return ColumnMapping(
                source_column=source_col,
                target=target,
                confidence=final_conf,
                method=MappingMethod.EXACT,
                rationale=f"Exact normalized match. VPF={vpf:.2f}.",
                evidence=evidence,
                review_required=final_conf < config.HIGH_CONFIDENCE_THRESHOLD,
                value_profile_fit=vpf,
                name_similarity=name_sim,
                method_agreement=1.0,
            )

    # --- Stage 2: Fuzzy ---
    fuzzy_result = _stage2_fuzzy(source_col)
    fuzzy_target = None
    if fuzzy_result:
        fuzzy_target, fuzzy_name_sim, fuzzy_evidence = fuzzy_result

    # --- Stage 3: Semantic ---
    semantic_result = _stage3_semantic(source_col)
    semantic_target = None
    if semantic_result:
        semantic_target, semantic_name_sim, semantic_evidence = semantic_result

    # Combine fuzzy + semantic
    best_target = None
    best_name_sim = 0.0
    best_evidence: List[str] = []
    method = MappingMethod.UNRESOLVED
    method_agreement = 0.5

    if fuzzy_target and semantic_target:
        if fuzzy_target == semantic_target:
            # Both agree
            best_target = fuzzy_target
            best_name_sim = (fuzzy_name_sim + semantic_name_sim) / 2
            best_evidence = fuzzy_evidence + semantic_evidence
            method = MappingMethod.FUZZY
            method_agreement = 1.0
        else:
            # Disagreement — pick higher confidence
            if fuzzy_name_sim >= semantic_name_sim:
                best_target = fuzzy_target
                best_name_sim = fuzzy_name_sim
                best_evidence = fuzzy_evidence
                method = MappingMethod.FUZZY
                method_agreement = 0.6
            else:
                best_target = semantic_target
                best_name_sim = semantic_name_sim
                best_evidence = semantic_evidence
                method = MappingMethod.SEMANTIC
                method_agreement = 0.6
    elif fuzzy_target:
        best_target = fuzzy_target
        best_name_sim = fuzzy_name_sim
        best_evidence = fuzzy_evidence
        method = MappingMethod.FUZZY
        method_agreement = 0.8
    elif semantic_target:
        best_target = semantic_target
        best_name_sim = semantic_name_sim
        best_evidence = semantic_evidence
        method = MappingMethod.SEMANTIC
        method_agreement = 0.8

    if best_target and best_target not in already_mapped:
        vpf = score_value_profile_fit(value_profile, best_target)
        final_conf = _compute_confidence(best_name_sim, vpf, method_agreement, method)

        if final_conf >= 0.50:
            return ColumnMapping(
                source_column=source_col,
                target=best_target,
                confidence=final_conf,
                method=method,
                rationale=f"Matched via {method.value}. VPF={vpf:.2f}.",
                evidence=best_evidence,
                review_required=final_conf < config.HIGH_CONFIDENCE_THRESHOLD,
                value_profile_fit=vpf,
                name_similarity=best_name_sim,
                method_agreement=method_agreement,
            )

    # --- Stage 4: LLM ---
    candidates = []
    if best_target:
        candidates.append((best_target, best_name_sim))
    # Add top value-profile candidates
    for field in TARGET_FIELDS:
        vpf_score = score_value_profile_fit(value_profile, field)
        if vpf_score > 0.3 and field not in already_mapped:
            candidates.append((field, vpf_score))
    candidates = sorted(candidates, key=lambda x: -x[1])[:5]

    llm_result = _stage4_llm(source_col, sample_values, candidates)
    if llm_result:
        llm_target, llm_conf, llm_evidence = llm_result
        if llm_target and llm_target not in already_mapped:
            vpf = score_value_profile_fit(value_profile, llm_target)
            final_conf = _compute_confidence(llm_conf, vpf, 0.7, MappingMethod.LLM)
            return ColumnMapping(
                source_column=source_col,
                target=llm_target,
                confidence=final_conf,
                method=MappingMethod.LLM,
                rationale=f"LLM reasoning. VPF={vpf:.2f}.",
                evidence=llm_evidence,
                review_required=True,  # LLM always requires review
                value_profile_fit=vpf,
                name_similarity=llm_conf,
                method_agreement=0.7,
            )

    # Unresolved
    return ColumnMapping(
        source_column=source_col,
        target=None,
        confidence=0.0,
        method=MappingMethod.UNRESOLVED,
        rationale="Could not confidently map this column to any target field.",
        evidence=["All mapping stages failed or returned no match."],
        review_required=True,
        value_profile_fit=0.0,
        name_similarity=0.0,
        method_agreement=0.0,
    )


# ---------------------------------------------------------------------------
# Hungarian assignment (1:1 constraint)
# ---------------------------------------------------------------------------

def _apply_hungarian_assignment(
    mappings: List[ColumnMapping],
) -> List[ColumnMapping]:
    """
    Ensure 1:1 mapping: if two source columns map to the same target,
    keep the higher-confidence one and mark the other as unresolved.
    """
    target_to_cols: Dict[str, List[int]] = {}
    for i, m in enumerate(mappings):
        if m.target:
            target_to_cols.setdefault(m.target, []).append(i)

    for target, indices in target_to_cols.items():
        if len(indices) > 1:
            # Sort by confidence descending
            indices.sort(key=lambda i: -mappings[i].confidence)
            # Keep best, demote rest
            for i in indices[1:]:
                old_target = mappings[i].target
                mappings[i] = mappings[i].model_copy(update={
                    "target": None,
                    "confidence": 0.0,
                    "method": MappingMethod.UNRESOLVED,
                    "rationale": (
                        f"Demoted: '{old_target}' already claimed by "
                        f"'{mappings[indices[0]].source_column}' "
                        f"with higher confidence."
                    ),
                    "review_required": True,
                })

    return mappings


# ---------------------------------------------------------------------------
# Agent 2 node function
# ---------------------------------------------------------------------------

def run_schema_mapping(state: SOVState) -> SOVState:
    """
    LangGraph node: Agent 2 — Schema Mapping.
    Reads: state.file_meta, state.sheet_manifest, state.header_row, state.primary_sheet_name
    Writes: state.mappings
    """
    logger.info("Agent 2: Schema Mapping starting.")
    state = state.model_copy(deep=True)
    state.stage = WorkflowStage.MAPPING

    if state.file_meta is None or state.sheet_manifest is None:
        state.error_message = "Missing file metadata or sheet manifest."
        state.stage = WorkflowStage.ERROR
        return state

    path = state.file_meta.temp_path
    sheet_name = state.primary_sheet_name or ""
    header_row = state.header_row

    # Load cleaned DataFrame
    try:
        df = unmerge_and_forward_fill(path, sheet_name)
        if df.empty:
            from app.processing.workbook import load_workbook_sheets
            sheets = load_workbook_sheets(path)
            df = sheets.get(sheet_name, pd.DataFrame())
    except Exception as e:
        state.error_message = f"Failed to load sheet for mapping: {e}"
        state.stage = WorkflowStage.ERROR
        return state

    data_df = extract_data_frame(df, header_row)
    source_columns = list(data_df.columns)
    logger.info("Mapping %d source columns.", len(source_columns))

    # Run cascade for each column
    raw_mappings: List[ColumnMapping] = []
    already_mapped: Set[str] = set()

    for col in source_columns:
        # Skip obviously bad column names
        if not col or col.startswith("_col_"):
            raw_mappings.append(ColumnMapping(
                source_column=col,
                target=None,
                confidence=0.0,
                method=MappingMethod.UNRESOLVED,
                rationale="Unnamed/index column — skipped.",
                evidence=[],
                review_required=False,
            ))
            continue

        mapping = map_column(col, data_df[col], already_mapped)
        if mapping.target:
            already_mapped.add(mapping.target)
        raw_mappings.append(mapping)

    # Apply 1:1 constraint
    final_mappings = _apply_hungarian_assignment(raw_mappings)

    # Compute summary stats
    mapped = [m for m in final_mappings if m.target is not None]
    unmapped_source = [m.source_column for m in final_mappings if m.target is None]
    unmapped_target = [f for f in TARGET_FIELDS if f not in {m.target for m in mapped}]
    overall_conf = sum(m.confidence for m in mapped) / max(len(mapped), 1)

    result = MappingResult(
        mappings=final_mappings,
        unmapped_source_columns=unmapped_source,
        unmapped_target_fields=unmapped_target,
        overall_mapping_confidence=round(overall_conf, 4),
    )

    state.mappings = result
    state.stage = WorkflowStage.MAPPED

    logger.info(
        "Agent 2 complete. Mapped: %d/%d columns. Overall confidence: %.3f.",
        len(mapped), len(source_columns), overall_conf,
    )
    return state
