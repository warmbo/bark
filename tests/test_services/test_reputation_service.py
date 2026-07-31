"""Tests for the reputation scoring service — level math, decay, caps, and tier resolution."""

from datetime import date

import pytest

from services.reputation_service import (
    DEFAULT_DAILY_CAP,
    DEFAULT_LEVEL_CONSTANT,
    DEFAULT_MESSAGE_POINTS,
    DEFAULT_REACTION_GIVEN_POINTS,
    DEFAULT_REACTION_RECEIVED_POINTS,
    DEFAULT_THANKS_GIVEN_POINTS,
    DEFAULT_THANKS_RECEIVED_POINTS,
    DEFAULT_VOICE_POINTS_PER_MINUTE,
    DEFAULT_WEEKLY_CAP,
    DEFAULT_WEEKLY_DECAY_RATE,
    check_daily_cap,
    check_weekly_cap,
    compute_decay,
    compute_emoji_points,
    compute_message_points,
    compute_reaction_given_points,
    compute_reaction_received_points,
    compute_thanks_given_points,
    compute_thanks_received_points,
    compute_voice_points,
    level_from_score,
    needs_monthly_reset,
    needs_weekly_reset,
    next_level_progress,
    resolve_tier,
    score_for_level,
)

# ── Level math ───────────────────────────────────────────────────────────


class TestLevelMath:
    def test_score_for_level_zero(self):
        assert score_for_level(0) == 0.0

    def test_score_for_level_one(self):
        assert score_for_level(1) == 50.0

    def test_score_for_level_five(self):
        assert score_for_level(5) == 1250.0

    def test_score_for_level_ten(self):
        assert score_for_level(10) == 5000.0

    def test_level_from_score_zero(self):
        assert level_from_score(0) == 0

    def test_level_from_score_barely_one(self):
        assert level_from_score(49) == 0

    def test_level_from_score_exactly_one(self):
        assert level_from_score(50) == 1

    def test_level_from_score_mid_one(self):
        assert level_from_score(100) == 1

    def test_level_from_score_exactly_two(self):
        # 2^2 * 50 = 200
        assert level_from_score(200) == 2

    def test_level_from_score_high_value(self):
        assert level_from_score(5050) == 10  # 10^2 * 50 = 5000, 11^2 * 50 = 6050
        assert level_from_score(6000) == 10
        assert level_from_score(6050) == 11

    def test_level_from_score_custom_constant(self):
        assert level_from_score(100, level_constant=25.0) == 2  # 2^2*25 = 100

    def test_next_level_progress_at_zero(self):
        progress = next_level_progress(0, 0, DEFAULT_LEVEL_CONSTANT)
        assert progress["current"] == 0
        assert progress["current_level_score"] == 0
        assert progress["next_level_score"] == 50
        assert progress["progress"] == 0.0
        assert progress["percent"] == 0.0

    def test_next_level_progress_halfway(self):
        progress = next_level_progress(25, 0, DEFAULT_LEVEL_CONSTANT)
        assert progress["percent"] == 50.0

    def test_next_level_progress_at_next(self):
        # At exactly level 1 score threshold (50)
        progress = next_level_progress(50, 1, DEFAULT_LEVEL_CONSTANT)
        assert progress["current"] == 50
        assert progress["current_level_score"] == 50
        # To get to level 2, need 200 total, so 150 more
        assert progress["next_level_score"] == 200
        assert progress["progress"] == 0.0  # 0 progress beyond level 1's threshold

    def test_next_level_progress_high_level(self):
        progress = next_level_progress(2500, 7, DEFAULT_LEVEL_CONSTANT)
        # 7^2*50 = 2450, 8^2*50 = 3200
        assert progress["current_level_score"] == 2450
        assert progress["next_level_score"] == 3200
        assert progress["current"] == 2500
        assert progress["percent"] > 0


# ── Point computation ────────────────────────────────────────────────────


class TestPointComputation:
    def test_message_points_default(self):
        assert compute_message_points({}) == DEFAULT_MESSAGE_POINTS

    def test_message_points_custom(self):
        assert compute_message_points({"weights": {"message": 2.5}}) == 2.5

    def test_reaction_received_default(self):
        assert compute_reaction_received_points({}) == DEFAULT_REACTION_RECEIVED_POINTS

    def test_reaction_given_default(self):
        assert compute_reaction_given_points({}) == DEFAULT_REACTION_GIVEN_POINTS

    def test_emoji_points_default(self):
        assert compute_emoji_points({}) == 1.0

    def test_thanks_given_default(self):
        assert compute_thanks_given_points({}) == DEFAULT_THANKS_GIVEN_POINTS

    def test_thanks_received_default(self):
        assert compute_thanks_received_points({}) == DEFAULT_THANKS_RECEIVED_POINTS

    def test_voice_points_default(self):
        assert compute_voice_points(10, {}) == 10 * DEFAULT_VOICE_POINTS_PER_MINUTE

    def test_voice_points_custom_weight(self):
        assert compute_voice_points(5, {"weights": {"voice_per_minute": 1.0}}) == 5.0

    def test_voice_points_zero_minutes(self):
        assert compute_voice_points(0, {}) == 0.0

    def test_voice_points_fractional(self):
        pts = compute_voice_points(0.5, {})
        assert pts == 0.5 * DEFAULT_VOICE_POINTS_PER_MINUTE


# ── Caps ─────────────────────────────────────────────────────────────────


class TestCaps:
    def test_daily_cap_below_limit(self):
        assert check_daily_cap(50, {}) == 50

    def test_daily_cap_at_limit(self):
        assert check_daily_cap(DEFAULT_DAILY_CAP, {}) == DEFAULT_DAILY_CAP

    def test_daily_cap_above_limit(self):
        assert check_daily_cap(500, {}) == DEFAULT_DAILY_CAP

    def test_daily_cap_custom(self):
        assert check_daily_cap(100, {"caps": {"daily": 50}}) == 50

    def test_daily_cap_zero(self):
        assert check_daily_cap(100, {"caps": {"daily": 0}}) == 0

    def test_weekly_cap_below_limit(self):
        assert check_weekly_cap(500, {}) == 500

    def test_weekly_cap_at_limit(self):
        assert check_weekly_cap(DEFAULT_WEEKLY_CAP, {}) == DEFAULT_WEEKLY_CAP

    def test_weekly_cap_above_limit(self):
        assert check_weekly_cap(2000, {}) == DEFAULT_WEEKLY_CAP


# ── Decay ─────────────────────────────────────────────────────────────────


class TestDecay:
    def test_no_decay_under_a_week(self):
        assert compute_decay(100, 5, DEFAULT_WEEKLY_DECAY_RATE) == 100

    def test_no_decay_exactly_a_week(self):
        assert compute_decay(100, 7, DEFAULT_WEEKLY_DECAY_RATE) == 100

    def test_decay_one_week_over(self):
        result = compute_decay(100, 14, DEFAULT_WEEKLY_DECAY_RATE)
        assert result == pytest.approx(95.0)  # 5% decay

    def test_decay_four_weeks(self):
        result = compute_decay(100, 35, DEFAULT_WEEKLY_DECAY_RATE)
        # 4 weeks of decay: 100 * 0.95^4
        assert result == pytest.approx(81.45, rel=0.01)

    def test_decay_to_zero(self):
        result = compute_decay(100, 365 * 10, 0.5)  # 50% weekly decay
        assert result == pytest.approx(0.0, abs=1e-10)

    def test_decay_custom_rate(self):
        result = compute_decay(100, 21, 0.1)  # 10% weekly
        # 2 weeks decay: 100 * 0.9^2 = 81
        assert result == pytest.approx(81.0)

    def test_decay_no_score(self):
        assert compute_decay(0, 100) == 0.0


# ── Tier resolution ──────────────────────────────────────────────────────


class TestTierResolution:
    def test_empty_tiers_returns_unranked(self):
        result = resolve_tier([], 0, 0)
        assert result["name"] == "unranked"
        assert result["symbol"] == "⬜"

    def test_lowest_tier_assigned(self):
        tiers = [
            {
                "name": "Bronze",
                "symbol": "🥉",
                "min_score": 50,
                "min_level": 1,
                "color_hex": "#cd7f32",
                "sort_order": 1,
            },
        ]
        result = resolve_tier(tiers, 1, 60)
        assert result["name"] == "Bronze"

    def test_highest_tier_matched(self):
        tiers = [
            {
                "name": "Bronze",
                "symbol": "🥉",
                "min_score": 50,
                "min_level": 1,
                "color_hex": "#cd7f32",
                "sort_order": 1,
            },
            {
                "name": "Silver",
                "symbol": "🥈",
                "min_score": 200,
                "min_level": 3,
                "color_hex": "#c0c0c0",
                "sort_order": 2,
            },
            {
                "name": "Gold",
                "symbol": "🥇",
                "min_score": 500,
                "min_level": 5,
                "color_hex": "#ffd700",
                "sort_order": 3,
            },
        ]
        result = resolve_tier(tiers, 6, 600)
        assert result["name"] == "Gold"

    def test_not_high_enough_for_any_tier(self):
        tiers = [
            {
                "name": "Bronze",
                "symbol": "🥉",
                "min_score": 50,
                "min_level": 1,
                "color_hex": "#cd7f32",
                "sort_order": 1,
            },
            {
                "name": "Silver",
                "symbol": "🥈",
                "min_score": 200,
                "min_level": 3,
                "color_hex": "#c0c0c0",
                "sort_order": 2,
            },
        ]
        result = resolve_tier(tiers, 0, 10)
        assert result["name"] == "unranked"

    def test_sort_order_overrides_position(self):
        tiers = [
            {
                "name": "Gold",
                "symbol": "🥇",
                "min_score": 500,
                "min_level": 5,
                "color_hex": "#ffd700",
                "sort_order": 3,
            },
            {
                "name": "Bronze",
                "symbol": "🥉",
                "min_score": 50,
                "min_level": 1,
                "color_hex": "#cd7f32",
                "sort_order": 1,
            },
            {
                "name": "Silver",
                "symbol": "🥈",
                "min_score": 200,
                "min_level": 3,
                "color_hex": "#c0c0c0",
                "sort_order": 2,
            },
        ]
        result = resolve_tier(tiers, 5, 600)
        # Gold has highest sort_order, should win
        assert result["name"] == "Gold"


# ── Weekly / Monthly reset ───────────────────────────────────────────────


class TestReset:
    def test_needs_weekly_reset_same_week(self):
        # Monday
        last = date(2026, 7, 27)
        # Same week, Tuesday
        today = date(2026, 7, 28)
        assert not needs_weekly_reset(last, today)

    def test_needs_weekly_reset_next_week(self):
        last = date(2026, 7, 20)  # Monday
        today = date(2026, 7, 28)  # Tuesday next week
        assert needs_weekly_reset(last, today)

    def test_needs_monthly_reset_same_month(self):
        last = date(2026, 7, 15)
        today = date(2026, 7, 28)
        assert not needs_monthly_reset(last, today)

    def test_needs_monthly_reset_next_month(self):
        last = date(2026, 7, 15)
        today = date(2026, 8, 1)
        assert needs_monthly_reset(last, today)
