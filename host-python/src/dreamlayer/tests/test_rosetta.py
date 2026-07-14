

def test_detect_language_handles_non_latin_scripts():
    """Audit 2026-07-14: non-Latin scripts were misread as English and never
    translated. A single CJK/Arabic/Cyrillic char is now decisive."""
    from dreamlayer.rosetta import detect_language
    assert detect_language("これはメニューです") == "ja"
    assert detect_language("这是菜单") == "zh"
    assert detect_language("هذه قائمة") == "ar"
    assert detect_language("это меню") == "ru"
    assert detect_language("this is a menu") == "en"
