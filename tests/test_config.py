from pathlib import Path

import pytest

from income_book_automation.config import (
    ClientConfigReadError,
    ClientConfigValidationError,
    list_client_profile_options,
    load_client_profile,
    load_client_profile_by_id,
)

VALID_CONFIG = """\
client_id: "client-001"
legal_name: "ФОП Тестовий Тарас Іванович"
tax_id: "0000000000"
own_accounts:
  - "UA273000010000000000000000001"
  - "UA973000010000000000000000002"
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
            "UA273000010000000000000000001",
            "UA973000010000000000000000002",
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


def test_load_client_profile_rejects_invalid_own_iban(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """\
client_id: "client-001"
legal_name: "ФОП Тестовий Тарас Іванович"
tax_id: "1111111111"
own_accounts:
  - "UA003000010000000000000000001"
""",
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


def test_lists_safe_client_options_and_loads_selected_profile(
    tmp_path: Path,
) -> None:
    config_directory = tmp_path / "clients"
    config_directory.mkdir()
    (config_directory / "second.yaml").write_text(
        """\
client_id: "client-002"
legal_name: "ФОП Яскравий Ярослав Іванович"
tax_id: "2222222222"
name_aliases:
  - "Яскравий Я.І."
""",
        encoding="utf-8",
    )
    (config_directory / "first.yml").write_text(
        """\
client_id: "client-001"
legal_name: "ФОП Абетка Анна Петрівна"
tax_id: "1111111111"
""",
        encoding="utf-8",
    )

    options = list_client_profile_options(config_directory)
    selected_profile = load_client_profile_by_id(
        config_directory,
        options[1].client_id,
    )

    assert [option.display_name for option in options] == [
        "Абетка Анна Петрівна",
        "Яскравий Ярослав Іванович",
    ]
    assert options[1].client_id.startswith("client-option-")
    assert options[1].client_id != "client-002"
    assert "Яскравий Я.І." in options[1].search_text
    assert "2222222222" not in options[1].search_text
    assert selected_profile.legal_name == "ФОП Яскравий Ярослав Іванович"


def test_rejects_unknown_client_id(tmp_path: Path) -> None:
    config_directory = tmp_path / "clients"
    config_directory.mkdir()
    (config_directory / "client.yaml").write_text(VALID_CONFIG, encoding="utf-8")

    with pytest.raises(
        ClientConfigValidationError,
        match="does not exist",
    ):
        load_client_profile_by_id(config_directory, "client-unknown")


def test_rejects_duplicate_client_ids(tmp_path: Path) -> None:
    config_directory = tmp_path / "clients"
    config_directory.mkdir()
    (config_directory / "first.yaml").write_text(VALID_CONFIG, encoding="utf-8")
    (config_directory / "second.yaml").write_text(VALID_CONFIG, encoding="utf-8")

    with pytest.raises(
        ClientConfigValidationError,
        match="duplicate client_id",
    ):
        list_client_profile_options(config_directory)
