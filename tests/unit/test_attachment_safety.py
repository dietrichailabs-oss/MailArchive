from mailarchive.attachments.store import sanitize_filename

def test_traversal_and_reserved_names_are_sanitized():
    assert '..' not in sanitize_filename('../../evil.exe')
    assert '/' not in sanitize_filename('../../evil.exe')
    assert '\\' not in sanitize_filename('..\\..\\evil.exe')
    assert sanitize_filename('CON').upper() != 'CON'
