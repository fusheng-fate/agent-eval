"""百分制改造验证：_seed_configs 分制迁移 + 配置默认值。

存量库的通过阈值若仍是 0-5 量级（≤5），启动时升到百分制默认 80；
管理员手动改过的更高值（>5）不动；非法值不动。
"""
from app.main import _seed_configs
from app.models import Config


def _set_threshold(db, value) -> None:
    db.add(Config(
        config_key="report.pass_threshold",
        config_value={"value": value},
        scope="global", editable_by="admin", description="通过阈值",
    ))
    db.commit()


def test_seed_creates_default_threshold_80(db):
    """全新库：seed 后 report.pass_threshold 默认 80（百分制）。"""
    _seed_configs(db)
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    assert pt is not None
    assert pt.config_value["value"] == 80


def test_seed_migrates_legacy_threshold_4_to_80(db):
    """存量库阈值 4（0-5 量级）→ 升到 80。"""
    _set_threshold(db, 4)
    _seed_configs(db)
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    assert pt.config_value["value"] == 80


def test_seed_migrates_legacy_threshold_5_to_80(db):
    """边界：阈值 5（仍属 0-5 量级）→ 升到 80。"""
    _set_threshold(db, 5)
    _seed_configs(db)
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    assert pt.config_value["value"] == 80


def test_seed_migrates_legacy_threshold_3_to_80(db):
    """存量库阈值 3 → 升到 80。"""
    _set_threshold(db, 3)
    _seed_configs(db)
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    assert pt.config_value["value"] == 80


def test_seed_keeps_admin_raised_threshold_90(db):
    """管理员已改成 90（>5，百分制量级）→ 不动。"""
    _set_threshold(db, 90)
    _seed_configs(db)
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    assert pt.config_value["value"] == 90


def test_seed_keeps_invalid_threshold(db):
    """非法值（非数字）→ 不动，不抛异常。"""
    _set_threshold(db, "abc")
    _seed_configs(db)
    pt = db.query(Config).filter(Config.config_key == "report.pass_threshold").first()
    assert pt.config_value["value"] == "abc"
