from mailarchive.viewer.sanitizer import sanitize_html


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
