from unittest.mock import MagicMock, patch

import pytest

from helpers_invoice_ocr import _parse_lines, extract_invoice_lines


def test_parse_plain_json():
    txt = '{"lines": [{"raw_description": "ALMAZA 33CL", "qty": 24, "unit_cost": 1.5}]}'
    out = _parse_lines(txt)
    assert out == [{"raw_description": "ALMAZA 33CL", "qty": 24.0, "unit_cost": 1.5}]


def test_parse_strips_code_fences():
    txt = '```json\n{"lines": [{"raw_description": "PEPSI 1L", "qty": 6, "unit_cost": null}]}\n```'
    out = _parse_lines(txt)
    assert out[0]["raw_description"] == "PEPSI 1L"
    assert out[0]["qty"] == 6.0
    assert out[0]["unit_cost"] is None


def test_parse_skips_blank_descriptions_and_bad_numbers():
    txt = '{"lines": [{"raw_description": "", "qty": 1}, {"raw_description": "X", "qty": "abc", "unit_cost": "2"}]}'
    out = _parse_lines(txt)
    assert len(out) == 1
    assert out[0]["raw_description"] == "X"
    assert out[0]["qty"] is None
    assert out[0]["unit_cost"] == 2.0


def test_parse_bad_json_raises():
    with pytest.raises(ValueError):
        _parse_lines("not json at all")
    with pytest.raises(ValueError):
        _parse_lines('{"nope": 1}')


def test_extract_sends_image_and_parses():
    fake_resp = MagicMock()
    fake_resp.output_text = '{"lines": [{"raw_description": "WATER 500ML", "qty": 12, "unit_cost": 0.3}]}'
    fake_client = MagicMock()
    fake_client.responses.create.return_value = fake_resp
    with patch("helpers_invoice_ocr._get_client", return_value=fake_client):
        out = extract_invoice_lines(b"\xff\xd8fakejpeg", media_type="image/jpeg")
    assert out[0]["raw_description"] == "WATER 500ML"
    kwargs = fake_client.responses.create.call_args.kwargs
    content = kwargs["input"][0]["content"]
    assert any(c.get("type") == "input_image" and c["image_url"].startswith("data:image/jpeg;base64,")
               for c in content)


def test_extract_empty_image_raises():
    with pytest.raises(ValueError):
        extract_invoice_lines(b"", media_type="image/jpeg")
