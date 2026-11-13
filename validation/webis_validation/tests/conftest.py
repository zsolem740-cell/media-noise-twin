import pytest

from validation.webis_validation import synthetic
from validation.webis_validation.isolation import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture
def corpus(tmp_path):
    inst, truth = synthetic.write_corpus(tmp_path / "data", n=400, seed=2)
    return tmp_path / "data", inst, truth
