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
from functools import lru_cache
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
from app.processing.workbook import load_source_data
from app.processing.profiling import profile_column, score_value_profile_fit
from app.config import config

logger = logging.getLogger(__name__)

# Confidence weights from PDF2
W_NAME = 0.45
W_VALUE = 0.35
W_METHOD = 0.20

# Memory boost cap
MEMORY_BOOST_CAP = 0.99

# Below this value-profile fit, a non-empty column's values contradict the
# target (e.g. building numbers 1..6 as "Building Value", $ amounts as
# "Number of Buildings", longitudes as "Country"). Such candidates are vetoed
# regardless of how well the header name matches.
MIN_PROFILE_FIT = 0.25


def _profile_contradicts(value_profile: Dict, vpf: float) -> bool:
    return not value_profile.get("empty", False) and vpf < MIN_PROFILE_FIT


def _profile_fit(value_profile: Dict, target: str) -> float:
    """
    Value-profile fit used for confidence. An empty column carries no evidence
    either way, so it scores neutral (0.5) instead of 0 — otherwise an empty but
    correctly named column ("No. of Bldgs") loses its target to any weak match.
    """
    if value_profile.get("empty", False):
        return 0.5
    return score_value_profile_fit(value_profile, target)


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

@lru_cache(maxsize=2048)
def _stage2_fuzzy_candidates(source_col: str, limit: int = 5) -> Tuple[Tuple[str, float, Tuple[str, ...]], ...]:
    """
    Returns up to `limit` distinct-target candidates above the fuzzy threshold,
    best first, as (target, confidence, evidence).
    """
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        logger.warning("RapidFuzz not available — skipping fuzzy stage.")
        return ()

    texts, targets = get_corpus()
    norm_src = normalize(source_col)
    norm_texts = [normalize(t) for t in texts]

    # Use token_sort_ratio for flexibility
    results = process.extract(
        norm_src,
        norm_texts,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=int(config.FUZZY_THRESHOLD * 100),
        limit=len(norm_texts),
    )

    candidates = []
    seen: Set[str] = set()
    for _match_text, score, idx in results:
        target = targets[idx]
        if target in seen:
            continue
        seen.add(target)
        evidence = (
            f"Fuzzy match: '{source_col}' ≈ '{texts[idx]}' (score={score:.1f}%)",
            f"Matched target: '{target}'",
        )
        candidates.append((target, (score / 100.0) * 0.92, evidence))  # slight discount for fuzzy
        if len(candidates) >= limit:
            break
    return tuple(candidates)


def _stage2_fuzzy(source_col: str) -> Optional[Tuple[str, float, List[str]]]:
    """Returns the best fuzzy (target, confidence, evidence) or None."""
    candidates = _stage2_fuzzy_candidates(source_col)
    if not candidates:
        return None
    target, conf, evidence = candidates[0]
    return target, conf, list(evidence)


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


@lru_cache(maxsize=2048)
def _stage3_semantic_candidates(source_col: str, limit: int = 5) -> Tuple[Tuple[str, float, Tuple[str, ...]], ...]:
    """
    Returns up to `limit` distinct-target candidates above the semantic
    threshold, best first, as (target, confidence, evidence).
    """
    try:
        from app.services.embeddings.encoder import embed_texts, batch_similarity

        query_emb = embed_texts([source_col])
        if query_emb is None:
            return ()

        corpus_emb = _get_corpus_embeddings()
        if corpus_emb is None:
            return ()

        texts, targets = get_corpus()
        sims = batch_similarity(query_emb[0], corpus_emb)
        order = sorted(range(len(sims)), key=lambda i: -sims[i])

        candidates = []
        seen: Set[str] = set()
        for idx in order:
            sim = sims[idx]
            if sim < config.SEMANTIC_THRESHOLD:
                break
            target = targets[idx]
            if target in seen:
                continue
            seen.add(target)
            evidence = (
                f"Semantic similarity: '{source_col}' ↔ '{texts[idx]}' = {sim:.3f}",
                f"Matched target: '{target}'",
            )
            candidates.append((target, sim * 0.90, evidence))  # slight discount for semantic
            if len(candidates) >= limit:
                break
        return tuple(candidates)
    except Exception as e:
        logger.warning("Semantic stage failed: %s", e)
        return ()


def _stage3_semantic(source_col: str) -> Optional[Tuple[str, float, List[str]]]:
    """Returns the best semantic (target, confidence, evidence) or None."""
    candidates = _stage3_semantic_candidates(source_col)
    if not candidates:
        return None
    target, conf, evidence = candidates[0]
    return target, conf, list(evidence)


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

        from app.services.llm.masking import mask_values
        sample_text = ", ".join(mask_values(sample_values[:5]))

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

def _unresolved(source_col: str, rationale: str, evidence: List[str]) -> ColumnMapping:
    return ColumnMapping(
        source_column=source_col,
        target=None,
        confidence=0.0,
        method=MappingMethod.UNRESOLVED,
        rationale=rationale,
        evidence=evidence,
        review_required=True,
        value_profile_fit=0.0,
        name_similarity=0.0,
        method_agreement=0.0,
    )


def map_column(
    source_col: str,
    series: pd.Series,
    already_mapped: Set[str],
    use_llm: bool = True,
) -> ColumnMapping:
    """
    Run the full cascade for a single source column.
    Every name-based candidate is cross-checked against the column's values;
    candidates whose value profile contradicts the target are vetoed.
    Returns a ColumnMapping.
    """
    # Profile values
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    value_profile = profile_column(series)

    # Sample values (limited, for LLM)
    sample_values = list(series.dropna().astype(str).head(config.LLM_SAMPLE_ROWS))
    vetoed: List[str] = []

    # --- Stage 0: Memory ---
    mem_result = _stage0_memory(source_col)
    if mem_result:
        target, conf, evidence = mem_result
        if target not in already_mapped:
            vpf = _profile_fit(value_profile, target)
            if _profile_contradicts(value_profile, vpf):
                vetoed.append(f"Memory suggested '{target}' but values contradict it (VPF={vpf:.2f}).")
            else:
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
            vpf = _profile_fit(value_profile, target)
            if _profile_contradicts(value_profile, vpf):
                vetoed.append(f"Header matches '{target}' but values contradict it (VPF={vpf:.2f}).")
            else:
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

    # --- Stage 2 + 3: Fuzzy and semantic candidates, scored jointly ---
    fuzzy = {t: (c, list(e)) for t, c, e in _stage2_fuzzy_candidates(source_col)}
    semantic = {t: (c, list(e)) for t, c, e in _stage3_semantic_candidates(source_col)}

    best: Optional[ColumnMapping] = None
    for target in list(dict.fromkeys(list(fuzzy) + list(semantic))):
        if target in already_mapped:
            continue
        if target in fuzzy and target in semantic:
            name_sim = (fuzzy[target][0] + semantic[target][0]) / 2
            evidence = fuzzy[target][1] + semantic[target][1]
            method, agreement = MappingMethod.FUZZY, 1.0
        elif target in fuzzy:
            name_sim, evidence = fuzzy[target]
            method, agreement = MappingMethod.FUZZY, 0.7
        else:
            name_sim, evidence = semantic[target]
            method, agreement = MappingMethod.SEMANTIC, 0.7

        vpf = _profile_fit(value_profile, target)
        if _profile_contradicts(value_profile, vpf):
            vetoed.append(f"'{target}' ({method.value}) vetoed: values contradict it (VPF={vpf:.2f}).")
            continue

        final_conf = _compute_confidence(name_sim, vpf, agreement, method)
        if final_conf >= 0.50 and (best is None or final_conf > best.confidence):
            best = ColumnMapping(
                source_column=source_col,
                target=target,
                confidence=final_conf,
                method=method,
                rationale=f"Matched via {method.value}. VPF={vpf:.2f}.",
                evidence=evidence + vetoed,
                review_required=final_conf < config.HIGH_CONFIDENCE_THRESHOLD,
                value_profile_fit=vpf,
                name_similarity=name_sim,
                method_agreement=agreement,
            )
    if best is not None:
        return best

    # --- Stage 4: LLM ---
    candidates = []
    for field in TARGET_FIELDS:
        vpf_score = score_value_profile_fit(value_profile, field)
        if vpf_score > 0.35 and field not in already_mapped:
            candidates.append((field, vpf_score))
    candidates = sorted(candidates, key=lambda x: -x[1])[:5]

    # Only call LLM if there is a plausible candidate with reasonable signal
    if not candidates:
        return _unresolved(
            source_col,
            "No candidate fields met minimum similarity threshold.",
            ["All mapping stages returned insufficient confidence."] + vetoed,
        )

    llm_result = _stage4_llm(source_col, sample_values, candidates) if use_llm else None
    if llm_result:
        llm_target, llm_conf, llm_evidence = llm_result
        if llm_target and llm_target not in already_mapped:
            vpf = _profile_fit(value_profile, llm_target)
            if not _profile_contradicts(value_profile, vpf):
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
    return _unresolved(
        source_col,
        "Could not confidently map this column to any target field.",
        ["All mapping stages failed or returned no match."] + vetoed,
    )


# ---------------------------------------------------------------------------
# Hungarian assignment (1:1 constraint)
# ---------------------------------------------------------------------------

def _apply_hungarian_assignment(
    mappings: List[ColumnMapping],
    column_sheets: Optional[Dict[str, List[str]]] = None,
) -> List[ColumnMapping]:
    """
    Ensure 1:1 mapping: if two source columns from the same sheet map to the
    same target, keep the higher-confidence one and mark the other as
    unresolved. Columns from different merged sheets may share a target.
    """
    column_sheets = column_sheets or {}

    def sheets_of(col: str) -> Set[str]:
        return set(column_sheets.get(col, ["_single_"]))

    target_to_cols: Dict[str, List[int]] = {}
    for i, m in enumerate(mappings):
        if m.target:
            target_to_cols.setdefault(m.target, []).append(i)

    for target, indices in target_to_cols.items():
        if len(indices) > 1:
            # Sort by confidence descending
            indices.sort(key=lambda i: -mappings[i].confidence)
            # Keep the best per sheet, demote columns that collide with it
            kept: List[int] = []
            for i in indices:
                rivals = [k for k in kept if sheets_of(mappings[k].source_column) & sheets_of(mappings[i].source_column)]
                if not rivals:
                    kept.append(i)
                    continue
                old_target = mappings[i].target
                mappings[i] = mappings[i].model_copy(update={
                    "target": None,
                    "confidence": 0.0,
                    "method": MappingMethod.UNRESOLVED,
                    "rationale": (
                        f"Demoted: '{old_target}' already claimed by "
                        f"'{mappings[rivals[0]].source_column}' "
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

    # Load cleaned DataFrame (all data sheets, stacked)
    try:
        data_df = load_source_data(state)
    except Exception as e:
        state.error_message = f"Failed to load sheet for mapping: {e}"
        state.stage = WorkflowStage.ERROR
        return state
    source_columns = list(data_df.columns)
    logger.info("Mapping %d source columns.", len(source_columns))

    def column_series(col: str) -> pd.Series:
        col_data = data_df[col]
        if isinstance(col_data, pd.DataFrame):
            col_data = col_data.iloc[:, 0]
        return col_data

    named_columns = [c for c in source_columns if c and not c.startswith("_col_")]

    # Pass 1: score every column independently (no LLM), so the order in which
    # targets are claimed reflects confidence rather than sheet position.
    # Otherwise an early weak match (e.g. "Account Name" → Reference) blocks a
    # later exact one ("Location ID" → Reference).
    independent = {
        col: map_column(col, column_series(col), set(), use_llm=False)
        for col in named_columns
    }
    # Pass 2: assign targets 1:1, always committing the strongest pending
    # column next. A column whose preferred target has been claimed is
    # re-scored and re-queued at its new (lower) confidence, so its fallback
    # never jumps ahead of a stronger column that wants the same target.
    # Targets are 1:1 *within a sheet*. When several data sheets are merged,
    # differently named columns from different sheets ("2023 Building Value",
    # "Building Value") may each claim the same target; their rows never overlap.
    column_sheets = data_df.attrs.get("column_sheets", {})

    def sheets_of(col: str) -> Set[str]:
        return set(column_sheets.get(col, ["_single_"]))

    claimed: Dict[str, Set[str]] = {}

    def blocked(col: str) -> Set[str]:
        return {t for t, sh in claimed.items() if sh & sheets_of(col)}

    current = dict(independent)
    pending = set(named_columns)
    by_column: Dict[str, ColumnMapping] = {}
    while pending:
        col = max(pending, key=lambda c: (current[c].confidence, -source_columns.index(c)))
        mapping = current[col]
        if mapping.target and mapping.target in blocked(col):
            current[col] = map_column(col, column_series(col), blocked(col), use_llm=False)
            continue
        if mapping.target is None:
            # Last resort for genuinely unresolved columns: LLM stage
            mapping = map_column(col, column_series(col), blocked(col), use_llm=True)
        pending.discard(col)
        if mapping.target:
            claimed.setdefault(mapping.target, set()).update(sheets_of(col))
        by_column[col] = mapping

    raw_mappings: List[ColumnMapping] = []
    for col in source_columns:
        if col in by_column:
            raw_mappings.append(by_column[col])
        else:
            # Skip obviously bad column names
            raw_mappings.append(ColumnMapping(
                source_column=col,
                target=None,
                confidence=0.0,
                method=MappingMethod.UNRESOLVED,
                rationale="Unnamed/index column — skipped.",
                evidence=[],
                review_required=False,
            ))

    # Apply 1:1 constraint
    final_mappings = _apply_hungarian_assignment(raw_mappings, column_sheets)

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
