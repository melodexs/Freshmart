"""Optional WhatsApp chat button: only appears for a valid number, and the link is safe."""

from __future__ import annotations

import sys

import pytest

from app.phone import whatsapp_link


@pytest.mark.parametrize(
    "raw",
    ["08012345678", "0801 234 5678", "+234 801 234 5678", "2348012345678", "801-234-5678"],
)
def test_every_way_of_typing_a_number_gives_the_same_international_link(raw):
    assert whatsapp_link(raw) == "https://wa.me/2348012345678"


@pytest.mark.parametrize("raw", ["", "12345", "0201234567", "not a number", "+44 7911 123456"])
def test_invalid_numbers_give_no_link(raw):
    assert whatsapp_link(raw) is None


def test_message_is_url_encoded_so_it_cannot_break_out_of_the_link():
    link = whatsapp_link("08012345678", 'Hi & "bye" <script>alert(1)</script>')
    assert link.startswith("https://wa.me/2348012345678?text=")
    assert "<" not in link and '"' not in link and " " not in link and "&bye" not in link


@pytest.fixture
def with_number(monkeypatch):
    """Start a fresh app (the client fixture reloads app.* modules) with the number set."""
    from fastapi.testclient import TestClient

    def make(number):
        monkeypatch.setenv("WHATSAPP_NUMBER", number)
        for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            del sys.modules[m]
        from app.main import app

        return TestClient(app)

    return make


def test_no_button_when_no_number_is_set(client):
    assert "whatsapp-fab" not in client.get("/").text


def test_no_button_when_the_number_is_invalid(client, with_number):
    with with_number("12345") as c:
        assert "whatsapp-fab" not in c.get("/").text


def test_button_appears_with_a_safe_link_when_the_number_is_valid(client, with_number):
    with with_number("0801 234 5678") as c:
        html = c.get("/").text
    assert 'class="whatsapp-fab"' in html
    assert 'href="https://wa.me/2348012345678?text=' in html
    assert 'rel="noopener noreferrer"' in html and 'target="_blank"' in html
