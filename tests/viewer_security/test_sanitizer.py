from mailarchive.viewer.sanitizer import sanitize_html


ZERO_WIDTH_FORMATS = '\u200b\u200c\u200d\ufeff\u2060'


def test_hostile_html_is_neutered():
    src='''<script>alert(1)</script><img src="https://tracker.test/x" onerror="boom()"><iframe src="http://evil"></iframe><a href="javascript:alert(1)">x</a><form action="https://evil"><input></form><p onclick="x()">ok</p>'''
    out=sanitize_html(src).lower()
    assert '<script' not in out and 'alert(1)' not in out
    assert 'https://tracker' not in out and 'onerror' not in out
    assert '<iframe' not in out and '<form' not in out
    assert 'javascript:' not in out and 'onclick' not in out
    assert '<p>ok</p>' in out


def test_file_and_data_links_removed():
    out=sanitize_html('<a href="file:///c:/secret">f</a><a href="data:text/html,x">d</a>')
    assert 'file:' not in out and 'data:' not in out


def test_dangerous_void_tags_do_not_swallow_following_message_body():
    src = (
        '<meta charset="utf-8">'
        '<link rel="stylesheet" href="https://tracker.invalid/style.css">'
        '<base href="https://evil.invalid/">'
        '<source src="https://evil.invalid/media">'
        '<embed src="https://evil.invalid/embed">'
        '<p>VISIBLE MESSAGE BODY</p>'
    )
    out = sanitize_html(src)
    lower = out.lower()
    for tag in ('meta', 'link', 'base', 'source', 'embed'):
        assert f'<{tag}' not in lower
    assert 'tracker.invalid' not in lower
    assert 'evil.invalid' not in lower
    assert '<p>VISIBLE MESSAGE BODY</p>' in out


def test_dangerous_container_subtrees_remain_suppressed():
    src = (
        '<script><p>SCRIPT SECRET</p></script>'
        '<style>.x{background:url(https://tracker.invalid/x)}</style>'
        '<iframe><p>FRAME SECRET</p></iframe>'
        '<p>SAFE AFTER DANGEROUS CONTAINERS</p>'
    )
    out = sanitize_html(src)
    assert 'SCRIPT SECRET' not in out
    assert 'FRAME SECRET' not in out
    assert 'tracker.invalid' not in out
    assert '<p>SAFE AFTER DANGEROUS CONTAINERS</p>' in out


def test_structural_only_safe_wrappers_collapse_to_literal_empty():
    src = (
        '<html><head><meta charset="utf-8"><script>HEAD EVIL</script></head>'
        '<body><iframe>FRAME EVIL</iframe><div><span>   </span></div></body></html>'
    )
    assert sanitize_html(src) == ''


def test_controlled_inline_image_only_html_counts_as_visible_content():
    out = sanitize_html(
        '<html><body><img src="cid:safe"></body></html>',
        cid_map={'safe': '/resource/archive-id/7'},
    )
    assert '/resource/archive-id/7' in out
    assert '<img' in out


def test_remote_image_only_html_collapses_to_empty():
    assert sanitize_html('<html><body><img src="https://tracker.invalid/pixel"></body></html>') == ''


def test_u200b_only_html_collapses_to_empty():
    assert sanitize_html('<html><body><p>\u200b</p></body></html>') == ''


def test_ufeff_only_html_collapses_to_empty():
    assert sanitize_html('<html><body><p>\ufeff</p></body></html>') == ''


def test_mixed_zero_width_format_only_html_collapses_to_empty():
    assert sanitize_html(f'<html><body><p>{ZERO_WIDTH_FORMATS}</p></body></html>') == ''


def test_zero_width_format_characters_adjacent_to_real_text_remain_visible():
    out = sanitize_html(f'<html><body><p>\u200bVISIBLE{ZERO_WIDTH_FORMATS}</p></body></html>')
    assert 'VISIBLE' in out


def test_controlled_inline_image_plus_zero_width_text_remains_visible():
    out = sanitize_html(
        f'<html><body><p>{ZERO_WIDTH_FORMATS}</p><img src="cid:safe"></body></html>',
        cid_map={'safe': '/resource/archive-id/7'},
    )
    assert '/resource/archive-id/7' in out
    assert '<img' in out
