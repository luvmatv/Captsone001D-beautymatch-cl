import huggingface_hub
import pytest
import sentence_transformers
from huggingface_hub.errors import LocalEntryNotFoundError

from src.matching import embeddings
from src.matching.embeddings import (
    EMBEDDING_DIMENSIONS,
    MODEL_NAME,
    ModelNotDownloaded,
    listing_text,
    load_model,
    to_pgvector,
)


def test_listing_text_prefixes_and_lowercases_brand_and_name() -> None:
    assert (
        listing_text("ANTONIO BANDERAS", "Blue Seduction Man EDT 200 mL")
        == "query: antonio banderas blue seduction man edt 200 ml"
    )


def test_listing_text_does_not_repeat_brand_already_in_name() -> None:
    assert (
        listing_text("Etienne", "Perfume Mujer Aura Violet  Etienne 100 Ml")
        == "query: perfume mujer aura violet etienne 100 ml"
    )


def test_listing_text_expands_abbreviations_before_checking_brand() -> None:
    assert (
        listing_text("ARIANA GRANDE", "ARIANA GR.MOD VAI.SP236ML")
        == "query: ariana grande mod vanilla spray 236 ml"
    )


def test_listing_text_without_brand() -> None:
    assert listing_text(None, "Colonia Pino 90 mL") == "query: colonia pino 90 ml"


def test_to_pgvector() -> None:
    assert to_pgvector([0.5, -0.25]) == "[0.5000000,-0.2500000]"


# ------------------------------------------ loading the model offline (daily run)


class FakeModel:
    created_with: dict = {}

    def __init__(self, name, **kwargs):
        FakeModel.created_with = {"name": name, **kwargs}

    def get_embedding_dimension(self):
        return EMBEDDING_DIMENSIONS


@pytest.fixture
def fake_model(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)  # restored after the test
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", FakeModel)
    FakeModel.created_with = {}


def test_offline_load_reads_only_local_files(monkeypatch, fake_model) -> None:
    checked = {}
    monkeypatch.setattr(huggingface_hub, "snapshot_download",
                        lambda name, **kwargs: checked.update(name=name, **kwargs) or "/cache/model")
    load_model(offline=True)
    assert checked == {"name": MODEL_NAME, "local_files_only": True}
    assert FakeModel.created_with["local_files_only"] is True
    assert embeddings.os.environ["HF_HUB_OFFLINE"] == "1"


def test_offline_load_fails_clearly_when_the_model_is_not_downloaded(monkeypatch, fake_model) -> None:
    def not_in_cache(name, **kwargs):
        raise LocalEntryNotFoundError("not in cache")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", not_in_cache)
    with pytest.raises(ModelNotDownloaded) as error:
        load_model(offline=True)
    assert MODEL_NAME in str(error.value) and "--download-model" in str(error.value)
    assert FakeModel.created_with == {}  # it did not even try to build the model


def test_online_load_is_unchanged(fake_model) -> None:
    load_model()
    assert FakeModel.created_with["local_files_only"] is False
    assert "HF_HUB_OFFLINE" not in embeddings.os.environ
