import dataclasses

import pytest

from jarvis.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        env="local",
        database_url=f"sqlite:///{tmp_path}/jarvis.db",
        tenants_file="config/tenants.example.yaml",
        data_source="sample",
        dry_run=True,
        output_dir=str(tmp_path / "out"),
        ai_provider="none",
    )


@pytest.fixture
def with_ai(settings):
    return dataclasses.replace(settings, ai_provider="anthropic")
