"""The char-ngram fallback must give the same answer on every run.

Layer 3 records a `relevance_score` for every retrieved document and asks a
journalist to act on the ordering. That ordering has to be reproducible: a
score that changes when the server restarts cannot be audited, cannot be cited,
and cannot be compared against a previous run of the same article.

The fallback used to bucket trigrams with Python's built-in `hash`, which is
salted per process, so an unchanged article scored differently after every
restart. These tests pin the fix by running the vectoriser in a genuinely
separate interpreter, which is the only place the old bug was visible.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from app.engines.embeddings import cosine_dense, ngram_vector

SAMPLE = "Ministers announced a coastal defence programme costing 1.2 billion pounds."

_BACKEND_DIR = Path(__file__).resolve().parent.parent

_SCRIPT = (
    "from app.engines.embeddings import ngram_vector;"
    "v = ngram_vector({text!r});"
    "print(','.join(f'{{x:.6f}}' for x in v))"
)


def _vector_in_a_fresh_process(text: str, seed: str) -> np.ndarray:
    """Compute the vector in a separate interpreter with a forced hash seed.

    A separate process is the point: PYTHONHASHSEED is fixed at interpreter
    start, so the bug this guards against was invisible from inside one test
    run however many times it was called.
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT.format(text=text)],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(_BACKEND_DIR),
        env=env,
    )
    return np.array([float(x) for x in result.stdout.strip().split(",")], dtype=np.float32)


def test_vector_is_identical_across_processes_with_different_hash_seeds() -> None:
    first = _vector_in_a_fresh_process(SAMPLE, "0")
    second = _vector_in_a_fresh_process(SAMPLE, "12345")

    # Under the old built-in hash these differed, and so did every score
    # derived from them.
    assert np.array_equal(first, second)
    assert float(np.linalg.norm(first)) > 0


def test_vector_matches_the_in_process_result() -> None:
    external = _vector_in_a_fresh_process(SAMPLE, "999")
    local = ngram_vector(SAMPLE)
    assert np.allclose(external, local, atol=1e-6)


def test_similarity_is_reproducible_across_processes() -> None:
    other = "Coastal defence work is due to begin in March, the department said."
    a1 = _vector_in_a_fresh_process(SAMPLE, "1")
    b1 = _vector_in_a_fresh_process(other, "1")
    a2 = _vector_in_a_fresh_process(SAMPLE, "777")
    b2 = _vector_in_a_fresh_process(other, "777")

    assert cosine_dense(a1, b1) == cosine_dense(a2, b2)


def test_identical_text_still_scores_one() -> None:
    vector = ngram_vector(SAMPLE)
    assert cosine_dense(vector, ngram_vector(SAMPLE)) == 1.0


def test_unrelated_text_scores_below_related_text() -> None:
    claim = ngram_vector("Coastal defence work begins in March.")
    related = ngram_vector(SAMPLE)
    unrelated = ngram_vector("The football result was announced after extra time.")
    assert cosine_dense(claim, related) > cosine_dense(claim, unrelated)
