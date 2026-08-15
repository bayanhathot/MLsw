"""Regression coverage for scripts/eval_preferences.py's labeled evaluation
-- the same run_eval() the script's own report uses, asserted against a
fixed seed so a future change that silently weakens preference-driven
ranking (e.g. an accidental WEIGHT_ENERGY_ALIGNMENT regression) fails a
test, not just a manually-run report."""

from scripts.eval_preferences import DEFAULT_SEED, run_eval


def test_a_learned_energy_preference_measurably_improves_ranked_precision():
    result = run_eval(seed=DEFAULT_SEED)

    assert result["baseline_intent_energy"] == "medium"
    assert result["biased_intent_energy"] == "high"
    # The concrete metric the "Long-term memory" completion criterion asked
    # for: a learned preference must produce a real, sizeable improvement in
    # how many of the top-K ranked candidates actually match it, not just a
    # theoretical intent change that never reaches ranking.
    assert result["biased_precision_at_k"] > result["baseline_precision_at_k"]
    assert result["biased_precision_at_k"] >= 0.8
    assert result["improvement"] >= 0.3


def test_the_eval_metric_is_deterministic_for_a_fixed_seed():
    first = run_eval(seed=777)
    second = run_eval(seed=777)
    assert first == second


def test_baseline_precision_reflects_pure_chance_on_the_unbiased_intent():
    # No preference, no genre, no mood -- ranking has nothing informative to
    # go on, so it should land close to the pool's true 50/50 energy/chill
    # split rather than accidentally favoring one label.
    result = run_eval(seed=DEFAULT_SEED)
    assert 0.2 <= result["baseline_precision_at_k"] <= 0.8
