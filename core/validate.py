"""Best-effort validators for generated site files.

Used by execute_loop to reject broken HTML/CSS/JS before it is committed to
the site directory, instead of discovering the break only when the user
opens the finished site.

Optional deps (tinycss2, esprima) are used if installed for real parsing;
otherwise falls back to cheap heuristic checks (tag/brace balance). Never
raises — always returns (ok: bool, error: str | None).
"""
import re

_BLOCK_TAGS = ("html", "head", "body", "div", "section", "header", "footer",
               "nav", "ul", "ol", "table", "main", "article", "form")


def validate_html(content):
    if not content or len(content.strip()) < 20:
        return False, "HTML content is empty or suspiciously short"
    if "<" not in content:
        return False, "No HTML tags found in content"

    for tag in _BLOCK_TAGS:
        opens = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", content, re.IGNORECASE))
        closes = len(re.findall(rf"</{tag}\s*>", content, re.IGNORECASE))
        if opens != closes:
            return False, f"Unbalanced <{tag}> tags: {opens} opening vs {closes} closing"

    try:
        from html.parser import HTMLParser

        class _Checker(HTMLParser):
            def error(self, message):
                raise ValueError(message)

        _Checker().feed(content)
    except Exception:
        pass  # html.parser is very lenient — soft errors are not fatal
    return True, None


def validate_css(content):
    if content is None:
        return False, "CSS content missing"
    if content.strip() == "":
        return True, None  # an intentionally empty CSS file is valid
    if content.count("{") != content.count("}"):
        return False, f"Unbalanced braces: {content.count('{')} open vs {content.count('}')} close"

    try:
        import tinycss2
        rules = tinycss2.parse_stylesheet(content, skip_whitespace=True)
        errors = [r.message for r in rules if r.type == "error"]
        if errors:
            return False, f"CSS parse errors: {errors[:3]}"
    except ImportError:
        pass  # optional dependency not installed — brace-balance check above stands
    return True, None


def validate_js(content):
    if content is None:
        return False, "JS content missing"
    if content.strip() == "":
        return True, None  # an intentionally empty JS file is valid

    for open_c, close_c, name in (("{", "}", "braces"), ("(", ")", "parens"), ("[", "]", "brackets")):
        if content.count(open_c) != content.count(close_c):
            return False, f"Unbalanced {name}: {content.count(open_c)} vs {content.count(close_c)}"

    try:
        import esprima
        esprima.parseScript(content)
    except ImportError:
        pass  # optional dependency not installed — bracket-balance check above stands
    except Exception as e:
        return False, f"JS syntax error: {e}"
    return True, None


def validate_file(path, content):
    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if ext == "html":
        return validate_html(content)
    if ext == "css":
        return validate_css(content)
    if ext == "js":
        return validate_js(content)
    return True, None
