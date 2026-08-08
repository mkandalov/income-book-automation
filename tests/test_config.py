from pathlib import Path

import pytest

from income_book_automation.config import (
    ClientConfigReadError,
    ClientConfigValidationError,
    load_client_profile,
)

VALID_CONFIG = """\
client_id: "client-001"
legal_name: "ФОП Тестовий Тарас Іванович"
tax_id: "0000000000"
own_accounts:
  - "UA000000000000000000000000001"
  - "UA000000000000000000000000002"
name_aliases:
  - "Тестовий Тарас Іванович"
"""


def _write_config(
    tmp_path: Path,
    contents: str,
) -> Path:
    config_path = tmp_path / "client.yaml"
    config_path.write_text(contents, encoding="utf-8")
    return config_path


def test_load_client_profile_from_valid_yaml(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, VALID_CONFIG)

    profile = load_client_profile(config_path)

    assert profile.client_id == "client-001"
    assert profile.legal_name == "ФОП Тестовий Тарас Іванович"
    assert profile.tax_id == "0000000000"
    assert profile.own_accounts == frozenset(
        {
            "UA000000000000000000000000001",
            "UA000000000000000000000000002",
        }
    )
    assert profile.name_aliases == frozenset({"Тестовий Тарас Іванович"})


def test_load_client_profile_raises_read_error_for_missing_file(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(ClientConfigReadError, match="cannot read client config"):
        load_client_profile(missing_path)


def test_load_client_profile_rejects_invalid_yaml(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        'client_id: "unterminated\n',
    )

    with pytest.raises(
        ClientConfigValidationError,
        match="invalid YAML",
    ):
        load_client_profile(config_path)


def test_load_client_profile_rejects_non_mapping_root(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        "- first\n- second\n",
    )

    with pytest.raises(
        ClientConfigValidationError,
        match="root must be a YAML mapping",
    ):
        load_client_profile(config_path)


def test_load_client_profile_rejects_missing_required_fields(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        'client_id: "client-001"\n',
    )

    with pytest.raises(
        ClientConfigValidationError,
        match="invalid client config fields",
    ):
        load_client_profile(config_path)


def test_load_client_profile_uses_optional_collection_defaults(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        """\
client_id: "client-002"
legal_name: "ФОП Приклад Олена Іванівна"
tax_id: "1111111111"
""",
    )

    profile = load_client_profile(config_path)

    assert profile.own_accounts == frozenset()
    assert profile.name_aliases == frozenset()


def test_example_client_config_is_valid() -> None:
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "clients" / "client.example.yaml"

    profile = load_client_profile(config_path)

    assert profile.client_id == "client-001"
