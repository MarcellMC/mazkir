from pathlib import Path


def item_name(item: dict) -> str:
    """Get item name from metadata, falling back to filename."""
    name = item["metadata"].get("name")
    if name:
        return name
    return Path(item["path"]).stem.replace("-", " ").replace("_", " ")
