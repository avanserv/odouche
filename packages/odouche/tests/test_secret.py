import copy
import logging
import pickle
from dataclasses import dataclass

import pytest

import odouche
from odouche import Secret


VALUE = "s3ss10n-v4lu3"
PLACEHOLDER = "**********"


@pytest.fixture
def secret():
    return Secret(VALUE)


def test_is_exported():
    assert "Secret" in odouche.__all__


def test_expose_secret_returns_the_value(secret):
    assert secret.expose_secret() == VALUE


def test_is_not_a_str(secret):
    assert not isinstance(secret, str)


@pytest.mark.parametrize("value", [None, b"bytes", 42, Secret(VALUE)])
def test_rejects_anything_but_a_str(value):
    with pytest.raises(TypeError) as raised:
        Secret(value)

    assert VALUE not in str(raised.value)


@pytest.mark.parametrize(
    "render",
    [
        repr,
        str,
        format,
        lambda secret: f"{secret}",
        lambda secret: f"{secret!r}",
        lambda secret: f"{secret:>20}",
        lambda secret: "%s %r" % (secret, secret),  # noqa: UP031
        "{}".format,
    ],
)
def test_renders_as_the_placeholder(secret, render):
    rendered = render(secret)

    assert VALUE not in rendered
    assert PLACEHOLDER in rendered


def test_logging_shows_the_placeholder(secret, caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("odouche.test").info("session %s %r", secret, secret)

    assert caplog.messages == [f"session {PLACEHOLDER} {PLACEHOLDER}"]
    assert VALUE not in caplog.text


def test_dataclass_repr_shows_the_placeholder(secret):
    @dataclass(frozen=True)
    class Holder:
        name: str
        session: Secret

    assert repr(Holder("dev", secret)) == f"{Holder.__qualname__}(name='dev', session={PLACEHOLDER})"


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_cannot_be_pickled(secret, protocol):
    with pytest.raises(TypeError):
        pickle.dumps(secret, protocol)


@pytest.mark.parametrize("duplicate", [copy.copy, copy.deepcopy])
def test_cannot_be_copied(secret, duplicate):
    with pytest.raises(TypeError):
        duplicate(secret)


def test_has_no_state_to_read(secret):
    with pytest.raises(TypeError):
        vars(secret)
    with pytest.raises(TypeError):
        secret.__getstate__()


def test_equality_compares_the_values(secret):
    assert secret == Secret(VALUE)
    assert secret != Secret("another")
    assert secret != VALUE


def test_cannot_be_hashed(secret):
    with pytest.raises(TypeError):
        hash(secret)
