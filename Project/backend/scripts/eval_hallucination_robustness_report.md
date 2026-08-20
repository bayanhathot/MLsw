# Adversarial hallucination-robustness evaluation

**Pass rate: 6/6 (100%)**

| # | Case | Result | Detail |
|---|------|--------|--------|
| 1 | Nonexistent/invented track name | ✅ PASS | Correctly reported no match via NoMatchingCandidate, invented nothing: No catalog or audius_multi_query candidate matched this request closely enough, and the catalog had nothing left to serve as a last resort either. |
| 2 | Silent upload | ✅ PASS | Correctly rejected: Audio appears to be silent or too quiet to be a usable track (measured level is below -50 dBFS). |
| 3 | Near-silent upload (~-60 dBFS noise) | ✅ PASS | Correctly rejected: Audio appears to be silent or too quiet to be a usable track (measured level is below -50 dBFS). |
| 4 | Corrupt/truncated file | ✅ PASS | Correctly rejected: Audio is too short to be a usable track (minimum 1 second). |
| 5 | Unavailable Audius URL | ✅ PASS | Degraded gracefully to a pass-through (reason: download_failed_http_400) |
| 6 | Malformed/malicious LLM JSON response | ✅ PASS | Every malformed/malicious response degraded to the safe deterministic fallback, no injected field reached the returned intent |
