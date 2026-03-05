"""
Unit tests voor Gatekeeper policy checks.

Draai met: python -m pytest control_api/tests/test_gatekeeper_policy.py -v
Of vanuit container: docker compose exec control_api python -m pytest /app/tests/ -v
"""

import pytest
import sys
import os

# Voeg de app dir toe aan sys.path zodat we server.py kunnen importeren
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# We importeren alleen de policy-functies, niet de FastAPI app
# (die vereist DB + env vars). Test de pure functies direct.

from server import (
    PARAM_BOUNDS,
    MAX_APPLIES_PER_DAY,
    FLASHCRASH_AUTO_ACTIONS,
    PROPOSAL_TYPES,
    _validate_param_bounds,
    _check_applies_limit,
    _applies_today,
)


class TestParamBounds:
    """Test PARAM_BOUNDS validatie en clamping."""

    def test_valid_params_no_violations(self):
        payload = {"rsi_buy_threshold": 30, "stoploss_pct": 3.0}
        violations = _validate_param_bounds(payload)
        assert violations == []
        assert payload["rsi_buy_threshold"] == 30
        assert payload["stoploss_pct"] == 3.0

    def test_param_too_low_gets_clamped(self):
        payload = {"rsi_buy_threshold": 10}  # min is 20
        violations = _validate_param_bounds(payload)
        assert len(violations) == 1
        assert "buiten grenzen" in violations[0]
        assert payload["rsi_buy_threshold"] == 20  # clamped to min

    def test_param_too_high_gets_clamped(self):
        payload = {"stoploss_pct": 10.0}  # max is 6.0
        violations = _validate_param_bounds(payload)
        assert len(violations) == 1
        assert payload["stoploss_pct"] == 6.0  # clamped to max

    def test_non_numeric_param_rejected(self):
        payload = {"rsi_buy_threshold": "abc"}
        violations = _validate_param_bounds(payload)
        assert len(violations) == 1
        assert "niet numeriek" in violations[0]

    def test_unknown_param_ignored(self):
        payload = {"unknown_param": 99}
        violations = _validate_param_bounds(payload)
        assert violations == []

    def test_all_bounds_at_min(self):
        payload = {k: lo for k, (lo, hi) in PARAM_BOUNDS.items()}
        violations = _validate_param_bounds(payload)
        assert violations == []

    def test_all_bounds_at_max(self):
        payload = {k: hi for k, (lo, hi) in PARAM_BOUNDS.items()}
        violations = _validate_param_bounds(payload)
        assert violations == []

    def test_multiple_violations(self):
        payload = {
            "rsi_buy_threshold": 5,     # too low (min 20)
            "stoploss_pct": 99.0,       # too high (max 6.0)
            "takeprofit_pct": 0.1,      # too low (min 3.0)
        }
        violations = _validate_param_bounds(payload)
        assert len(violations) == 3
        # Check clamping
        assert payload["rsi_buy_threshold"] == 20
        assert payload["stoploss_pct"] == 6.0
        assert payload["takeprofit_pct"] == 3.0


class TestAppliesLimit:
    """Test dagelijkse applies limiet."""

    def test_within_limit(self):
        _applies_today["date"] = ""
        _applies_today["count"] = 0
        # Should not raise
        _check_applies_limit()
        assert _applies_today["count"] == 0  # check doesn't increment

    def test_at_limit_raises(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _applies_today["date"] = today
        _applies_today["count"] = MAX_APPLIES_PER_DAY

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _check_applies_limit()
        assert exc_info.value.status_code == 429

    def test_resets_on_new_day(self):
        _applies_today["date"] = "2020-01-01"  # old date
        _applies_today["count"] = 99
        _check_applies_limit()
        assert _applies_today["count"] == 0  # reset


class TestFlashCrashActions:
    """Test flash-crash auto-apply policy."""

    def test_pause_is_auto_action(self):
        assert "PAUSE" in FLASHCRASH_AUTO_ACTIONS

    def test_no_buy_is_auto_action(self):
        assert "NO_BUY" in FLASHCRASH_AUTO_ACTIONS

    def test_exit_only_is_auto_action(self):
        assert "EXIT_ONLY" in FLASHCRASH_AUTO_ACTIONS

    def test_param_change_not_auto(self):
        assert "PARAM_CHANGE" not in FLASHCRASH_AUTO_ACTIONS

    def test_resume_not_auto(self):
        assert "RESUME" not in FLASHCRASH_AUTO_ACTIONS

    def test_deploy_not_auto(self):
        assert "DEPLOY_STAGING" not in FLASHCRASH_AUTO_ACTIONS


class TestProposalTypes:
    """Test dat alle verwachte proposal types bestaan."""

    def test_all_types_present(self):
        expected = {"PAUSE", "RESUME", "PARAM_CHANGE", "COIN_ALLOW", "RUN_BACKTEST", "DEPLOY_STAGING"}
        assert expected == PROPOSAL_TYPES


class TestAllowLiveBlocked:
    """Test dat ALLOW_LIVE nooit via payload kan worden ingesteld."""

    def test_allow_live_not_in_bounds(self):
        # ALLOW_LIVE mag niet als parameter bestaan
        assert "ALLOW_LIVE" not in PARAM_BOUNDS
        assert "allow_live" not in PARAM_BOUNDS
