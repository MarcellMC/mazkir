"""Guards the capture skill declares create_event so timed events aren't mis-filed."""

from src.config import settings
from src.services.skill_registry import SkillRegistry


def test_capture_skill_has_create_event():
    registry = SkillRegistry(skills_dir=settings.skills_dir)
    registry.load()
    capture = registry.get("capture")
    assert capture is not None, f"capture skill not found in {settings.skills_dir}"
    assert "create_event" in capture.tools
