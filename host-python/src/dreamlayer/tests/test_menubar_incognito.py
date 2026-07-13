"""P1-11: the menu-bar Incognito toggle must not force the cloud on.

The rumps menu bar had no cloud preference of its own, yet posted
cloud_enabled = not incognito — so turning incognito *off* silently
re-enabled the opt-in-off cloud tier. The fix posts only network_mode; these
tests pin the server contract that makes that correct: lan_only forces cloud
off on its own, and toggling network_mode leaves the remembered cloud_enabled
untouched. (rumps is macOS-only, so we verify the Brain-side behavior the menu
bar now relies on rather than the widget.)
"""
from __future__ import annotations

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.store import BrainConfig


def test_incognito_toggle_preserves_cloud_preference(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # user has opted the cloud ON and configured it
    BrainConfig(cloud_enabled=True, cloud_api_key="k", cloud_model="m").save(cfg)
    brain = Brain(cfg)
    assert brain.config.cloud_enabled is True and brain.config.cloud_ready()

    # menu bar goes incognito → posts ONLY network_mode
    brain.apply_config({"network_mode": "lan_only"})
    assert brain.config.cloud_enabled is True          # preference preserved
    assert brain.config.cloud_ready() is False          # lan_only forces off

    # menu bar leaves incognito → the remembered preference returns, not force-on
    brain.apply_config({"network_mode": "connected"})
    assert brain.config.cloud_enabled is True
    assert brain.config.cloud_ready() is True


def test_incognito_off_does_not_resurrect_a_disabled_cloud(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # user has the cloud OFF (the opt-in default)
    BrainConfig(cloud_enabled=False, cloud_api_key="k", cloud_model="m").save(cfg)
    brain = Brain(cfg)
    brain.apply_config({"network_mode": "lan_only"})    # go incognito
    brain.apply_config({"network_mode": "connected"})   # leave it
    # the old bug: cloud_enabled would now be True. It must stay False.
    assert brain.config.cloud_enabled is False
    assert brain.config.cloud_ready() is False
