"""Load and validate private client configuration."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from income_book_automation.models import ClientProfile


class ClientConfigError(Exception):
    """Base error raised while loading client configuration."""


class ClientConfigReadError(ClientConfigError):
    """Raised when the configuration file cannot be read."""


class ClientConfigValidationError(ClientConfigError):
    """Raised when configuration contents are invalid."""


def load_client_profile(config_path: Path) -> ClientProfile:
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClientConfigReadError(
            f"cannot read client config: {config_path}"
        ) from exc

    try:
        raw_config = yaml.safe_load(config_text)
    except yaml.YAMLError as exc:
        raise ClientConfigValidationError(
            f"invalid YAML in client config: {config_path}"
        ) from exc

    if not isinstance(raw_config, dict):
        raise ClientConfigValidationError("client config root must be a YAML mapping")

    try:
        return ClientProfile.model_validate(raw_config)
    except ValidationError as exc:
        raise ClientConfigValidationError(
            f"invalid client config fields: {config_path}"
        ) from exc
