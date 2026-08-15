from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook

from income_book_automation.client_profile_generator import (
    ClientProfileGenerationError,
    generate_client_profiles,
)
from income_book_automation.models import ClientProfile


def _create_register(
    path: Path,
    rows: list[tuple[object, object, object]],
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("№", "ПІБ", "ІПН"))
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def test_generates_valid_profiles_and_name_aliases(tmp_path: Path) -> None:
    register_path = tmp_path / "clients.xlsx"
    output_directory = tmp_path / "profiles"
    _create_register(
        register_path,
        [
            (1, "Тестовий Тарас Іванович", "1234567890"),
            (2, "ФОП Приклад Олена", "0987654321"),
        ],
    )

    count = generate_client_profiles(
        register_path,
        output_directory,
        expected_count=2,
    )

    assert count == 2
    generated_files = sorted(output_directory.glob("*.yaml"))
    assert [path.name for path in generated_files] == [
        "001_Тестовий_Тарас.yaml",
        "002_Приклад_Олена.yaml",
    ]

    first_config = yaml.safe_load(generated_files[0].read_text(encoding="utf-8"))
    profile = ClientProfile.model_validate(first_config)

    assert profile.legal_name == "ФОП Тестовий Тарас Іванович"
    assert profile.tax_id == "1234567890"
    assert profile.client_id.startswith("client-")
    assert profile.tax_id not in profile.client_id
    assert profile.own_accounts == frozenset()
    assert "Тестовий Т.І." in profile.name_aliases
    assert "ФОП Тестовий Т. І." in profile.name_aliases

    second_config = yaml.safe_load(generated_files[1].read_text(encoding="utf-8"))
    second_profile = ClientProfile.model_validate(second_config)
    assert "Приклад О." in second_profile.name_aliases
    assert "ФОП Приклад О." in second_profile.name_aliases


def test_preserves_tax_id_leading_zero_from_cell_format(tmp_path: Path) -> None:
    register_path = tmp_path / "clients.xlsx"
    output_directory = tmp_path / "profiles"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("№", "ПІБ", "РНОКПП"))
    sheet.append((1, "Тестовий Тарас Іванович", 123456789))
    sheet["C2"].number_format = "0000000000"
    workbook.save(register_path)
    workbook.close()

    generate_client_profiles(register_path, output_directory)

    config = yaml.safe_load(
        next(output_directory.glob("*.yaml")).read_text(encoding="utf-8")
    )
    assert config["tax_id"] == "0123456789"


def test_dry_run_validates_without_creating_output(tmp_path: Path) -> None:
    register_path = tmp_path / "clients.xlsx"
    output_directory = tmp_path / "profiles"
    _create_register(
        register_path,
        [(1, "Тестовий Тарас Іванович", "1234567890")],
    )

    count = generate_client_profiles(
        register_path,
        output_directory,
        expected_count=1,
        dry_run=True,
    )

    assert count == 1
    assert not output_directory.exists()


def test_rejects_duplicate_tax_ids_before_writing(tmp_path: Path) -> None:
    register_path = tmp_path / "clients.xlsx"
    output_directory = tmp_path / "profiles"
    _create_register(
        register_path,
        [
            (1, "Перший Тарас Іванович", "1234567890"),
            (2, "Другий Олена Петрівна", "1234567890"),
        ],
    )

    with pytest.raises(ClientProfileGenerationError, match="Duplicate tax ID"):
        generate_client_profiles(register_path, output_directory)

    assert not output_directory.exists()


def test_rejects_unexpected_client_count(tmp_path: Path) -> None:
    register_path = tmp_path / "clients.xlsx"
    output_directory = tmp_path / "profiles"
    _create_register(
        register_path,
        [(1, "Тестовий Тарас Іванович", "1234567890")],
    )

    with pytest.raises(ClientProfileGenerationError, match="Expected 179"):
        generate_client_profiles(
            register_path,
            output_directory,
            expected_count=179,
        )

    assert not output_directory.exists()


def test_refuses_to_mix_with_existing_yaml_files(tmp_path: Path) -> None:
    register_path = tmp_path / "clients.xlsx"
    output_directory = tmp_path / "profiles"
    output_directory.mkdir()
    (output_directory / "old.yaml").write_text("old: true\n", encoding="utf-8")
    _create_register(
        register_path,
        [(1, "Тестовий Тарас Іванович", "1234567890")],
    )

    with pytest.raises(ClientProfileGenerationError, match="already contains"):
        generate_client_profiles(register_path, output_directory)
