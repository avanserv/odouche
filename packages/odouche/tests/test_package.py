from importlib.metadata import version

import odouche


def test_version_matches_distribution_metadata():
    assert odouche.__version__ == version("odouche")
