"""Load, validate and discover private client configuration."""

import hashlib
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ClientProfileOption:
    """Safe subset of a client profile exposed to the web form."""

    client_id: str
    display_name: str
    search_text: str


def load_client_profile(config_path: Path) -> ClientProfile:
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
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


def _client_config_paths(config_directory: Path) -> list[Path]:
    if not config_directory.is_dir():
        raise ClientConfigReadError(
            f"client configuration directory does not exist: {config_directory}"
        )

    paths = sorted(
        (*config_directory.glob("*.yaml"), *config_directory.glob("*.yml")),
        key=lambda path: path.name.casefold(),
    )

    if not paths:
        raise ClientConfigReadError(f"no client profiles found in: {config_directory}")

    return paths


def _display_name(profile: ClientProfile) -> str:
    legal_name = " ".join(profile.legal_name.split())

    if legal_name.casefold().startswith("фоп "):
        return legal_name[4:].strip()

    return legal_name


def _public_client_id(internal_client_id: str) -> str:
    digest = hashlib.sha256(internal_client_id.encode("utf-8")).hexdigest()[:20]
    return f"client-option-{digest}"


def _load_client_catalog(
    config_directory: Path,
) -> list[tuple[ClientProfile, ClientProfileOption]]:
    catalog: list[tuple[ClientProfile, ClientProfileOption]] = []
    seen_ids: dict[str, Path] = {}

    for config_path in _client_config_paths(config_directory):
        profile = load_client_profile(config_path)
        previous_path = seen_ids.get(profile.client_id)

        if previous_path is not None:
            raise ClientConfigValidationError(
                "duplicate client_id in configuration files: "
                f"{previous_path.name}, {config_path.name}"
            )

        seen_ids[profile.client_id] = config_path
        display_name = _display_name(profile)
        search_terms = [display_name, profile.legal_name, *profile.name_aliases]
        option = ClientProfileOption(
            client_id=_public_client_id(profile.client_id),
            display_name=display_name,
            search_text=" ".join(dict.fromkeys(search_terms)),
        )
        catalog.append((profile, option))

    return catalog


def list_client_profile_options(
    config_directory: Path,
) -> tuple[ClientProfileOption, ...]:
    """Return client names and opaque identifiers for the web selector."""
    options = (option for _profile, option in _load_client_catalog(config_directory))
    return tuple(sorted(options, key=lambda option: option.display_name.casefold()))


def load_client_profile_by_id(
    config_directory: Path,
    client_id: str,
) -> ClientProfile:
    """Resolve a submitted opaque client ID inside the configured directory."""
    normalized_client_id = client_id.strip()

    if not normalized_client_id:
        raise ClientConfigValidationError("client profile was not selected")

    for profile, _option in _load_client_catalog(config_directory):
        if _option.client_id == normalized_client_id:
            return profile

    raise ClientConfigValidationError("selected client profile does not exist")
