import os
import pytest

TOP_DIR = os.environ["TOP_DIR"]


@pytest.fixture(scope="session")
def top_dir():
    return TOP_DIR
