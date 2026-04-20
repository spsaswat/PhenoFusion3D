"""
tests/test_registration_agent.py
--------------------------------
Unit tests for the registration agent's judging core.

These tests intentionally avoid Open3D so they run fast and exercise the
policy logic in isolation. Recovery strategy helpers (which DO use Open3D)
are covered by integration runs against real captures.
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.registration_agent import (
    AgentConfig, RegistrationAgent, FrameDecision,
    rotation_magnitude_deg, translation_magnitude_m,
)


def _T(tx=0.0, ty=0.0, tz=0.0):
    """Pure-translation 4x4 transform."""
    T = np.eye(4)
    T[:3, 3] = [tx, ty, tz]
    return T


# --------------------------------------------------------------- thresholds

def test_cold_start_uses_only_floors():
    """During cold start, thresholds must equal the absolute floors regardless
    of the (small) accepted history."""
    cfg = AgentConfig(cold_start_frames=5, floor_min_fitness=0.3,
                      floor_max_rmse=0.015, window_size=20)
    agent = RegistrationAgent(cfg)

    # Feed a few "good" accepts but stay under cold_start_frames.
    for _ in range(4):
        agent.record_accept(0.9, 0.001, _T(tx=0.001))

    min_fit, max_rmse = agent.current_thresholds()
    assert min_fit == cfg.floor_min_fitness
    assert max_rmse == cfg.floor_max_rmse


def test_adaptive_threshold_tightens_after_window():
    """After cold start, a clean run of high-fitness/low-rmse frames should
    tighten the thresholds beyond the absolute floors."""
    cfg = AgentConfig(cold_start_frames=3, fitness_k_mad=1.0, rmse_k_mad=1.0,
                      floor_min_fitness=0.3, floor_max_rmse=0.015,
                      window_size=20)
    agent = RegistrationAgent(cfg)

    # Cold start window of varied-but-good values to give MAD > 0.
    for f, r in [(0.85, 0.004), (0.90, 0.005), (0.88, 0.003), (0.92, 0.006),
                 (0.86, 0.004), (0.91, 0.005)]:
        agent.record_accept(f, r, _T(tx=0.001))

    min_fit, max_rmse = agent.current_thresholds()
    # Adaptive should TIGHTEN: max_rmse below the 0.015 ceiling. min_fit may be
    # clamped to the floor (since median-k*MAD can be > 0.3), which is fine,
    # but max_rmse must visibly tighten on this sample.
    assert max_rmse < cfg.floor_max_rmse
    assert min_fit >= cfg.floor_min_fitness  # floor clamp still respected


# ----------------------------------------------------------------- judge

def test_good_frame_accepts():
    cfg = AgentConfig()
    agent = RegistrationAgent(cfg)
    d = agent.judge(0.85, 0.003, _T(tx=0.001), expected_step_m=0.001)
    assert d.action == 'accept'


def test_low_fitness_triggers_retry():
    cfg = AgentConfig(max_retries=5)
    agent = RegistrationAgent(cfg)
    d = agent.judge(0.05, 0.003, _T(tx=0.001), expected_step_m=0.001, attempt=0)
    assert d.action == 'retry'
    assert d.next_strategy is not None


def test_persistent_low_fitness_eventually_rejects():
    """Past max_retries with no recovery, the agent must reject."""
    cfg = AgentConfig(max_retries=3, enable_feature_init=False)
    agent = RegistrationAgent(cfg)
    d = agent.judge(0.05, 0.003, _T(tx=0.001), expected_step_m=0.001, attempt=3)
    assert d.action == 'reject'


def test_huge_translation_jump_triggers_retry():
    """A 50 mm jump when expected step is 1 mm -- well past the 3x cap."""
    cfg = AgentConfig(max_trans_factor=3.0, abs_trans_cap_m=0.005)
    agent = RegistrationAgent(cfg)
    d = agent.judge(0.9, 0.003, _T(tx=0.05), expected_step_m=0.001, attempt=0)
    assert d.action == 'retry'
    assert 'translation' in d.reason


def test_huge_rotation_triggers_retry():
    cfg = AgentConfig(rot_max_deg=10.0)
    agent = RegistrationAgent(cfg)
    # 30deg rotation about Z.
    a = np.deg2rad(30.0)
    R = np.array([[np.cos(a), -np.sin(a), 0],
                  [np.sin(a),  np.cos(a), 0],
                  [0,          0,         1]])
    T = np.eye(4); T[:3, :3] = R
    d = agent.judge(0.9, 0.003, T, expected_step_m=0.001, attempt=0)
    assert d.action == 'retry'
    assert 'rotation' in d.reason


# ---------------------------------------------------------- fallback ref

def test_three_consecutive_rejects_triggers_fallback():
    cfg = AgentConfig(fallback_after_rejects=3)
    agent = RegistrationAgent(cfg)
    assert not agent.should_fallback_reference()
    agent.record_reject()
    agent.record_reject()
    assert not agent.should_fallback_reference()
    agent.record_reject()
    assert agent.should_fallback_reference()


def test_accept_resets_consecutive_rejects():
    cfg = AgentConfig(fallback_after_rejects=3)
    agent = RegistrationAgent(cfg)
    agent.record_reject(); agent.record_reject()
    agent.record_accept(0.9, 0.003, _T(tx=0.001))
    assert agent.consecutive_rejects == 0
    assert not agent.should_fallback_reference()


# ---------------------------------------------------------- recovery list

def test_feature_init_disabled_by_default():
    cfg = AgentConfig()  # enable_feature_init=False
    agent = RegistrationAgent(cfg)
    strategies = [agent.next_recovery(i) for i in range(10)
                  if agent.next_recovery(i) is not None]
    assert 'feature_init' not in strategies


def test_feature_init_enabled_when_opt_in():
    cfg = AgentConfig(enable_feature_init=True, max_retries=10)
    agent = RegistrationAgent(cfg)
    strategies = [agent.next_recovery(i) for i in range(10)
                  if agent.next_recovery(i) is not None]
    assert 'feature_init' in strategies


def test_next_recovery_runs_out():
    cfg = AgentConfig(max_retries=2)
    agent = RegistrationAgent(cfg)
    assert agent.next_recovery(0) is not None
    assert agent.next_recovery(1) is not None
    assert agent.next_recovery(2) is None  # capped


# ------------------------------------------------------------ math helpers

def test_translation_magnitude():
    assert abs(translation_magnitude_m(_T(tx=0.003, ty=0.004)) - 0.005) < 1e-9


def test_rotation_magnitude_zero_for_identity():
    assert rotation_magnitude_deg(np.eye(4)) < 1e-6


def test_rotation_magnitude_90deg():
    a = np.deg2rad(90.0)
    R = np.array([[np.cos(a), -np.sin(a), 0],
                  [np.sin(a),  np.cos(a), 0],
                  [0,          0,         1]])
    T = np.eye(4); T[:3, :3] = R
    assert abs(rotation_magnitude_deg(T) - 90.0) < 1e-6
