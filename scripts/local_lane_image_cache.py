"""Local transfer of locked images into lane sandboxes.

The host daemon already holds the images named by infra/services.lock.json.
Saving and loading those images is refused in this revision: callers receive a
typed error, and no registry pull is attempted.
"""

from __future__ import annotations

from pathlib import Path

from run_qualifying_campaign import CampaignError


def locked_image_pins(document: object) -> list[dict[str, str]]:
    del document
    raise CampaignError("image cache is not implemented")


def parse_host_inspect(text: str, pinned_reference: str) -> str:
    del text, pinned_reference
    raise CampaignError("image cache is not implemented")


def parse_loaded_inspect(text: str, image_id: str) -> None:
    del text, image_id
    raise CampaignError("image cache is not implemented")


def archive_image_id_matches(archive: Path, image_id: str) -> None:
    del archive, image_id
    raise CampaignError("image cache is not implemented")


def prepare_image_cache(
    lock_path: Path, destination: Path, runner: object, *, timeout: object
) -> dict[str, object]:
    del lock_path, destination, runner, timeout
    raise CampaignError("image cache is not implemented")


def verify_image_cache(cache_dir: Path, lock_path: Path) -> dict[str, object]:
    del cache_dir, lock_path
    raise CampaignError("image cache is not implemented")
