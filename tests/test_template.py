import pytest

from hi.template import TemplateError, render, render_obj


def test_render_paths_and_json():
    ctx = {"request": {"task": "fix it", "files": ["a", "b"], "model": None}, "ws": "/w"}
    assert render("{request.task} in {ws}", ctx) == "fix it in /w"
    assert render("{request.files}", ctx) == '["a", "b"]'
    assert render("[{request.model}]", ctx) == "[]"
    assert render_obj(["{ws}/x", {"k": "{request.task}"}], ctx) == ["/w/x", {"k": "fix it"}]


def test_missing_raises():
    with pytest.raises(TemplateError):
        render("{nope.x}", {})
