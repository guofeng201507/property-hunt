from datetime import date

from property_hunt import normalize


def test_parse_mmyy():
    assert normalize.parse_mmyy("0324") == date(2024, 3, 1)
    assert normalize.parse_mmyy("1226") == date(2026, 12, 1)
    assert normalize.parse_mmyy("bad") is None


def test_parse_tenure():
    assert normalize.parse_tenure("Freehold") == ("FREEHOLD", None)
    assert normalize.parse_tenure("99 yrs lease commencing from 2007") == ("LEASEHOLD_99", 2007)
    assert normalize.parse_tenure("999 yrs lease commencing from 1995") == ("LEASEHOLD_999", 1995)


def test_normalize_property_type():
    assert normalize.normalize_property_type("Semi-detached") == "SEMI_D"
    assert normalize.normalize_property_type("Semi-Detached House") == "SEMI_D"
    assert normalize.normalize_property_type("Terrace House") == "TERRACE"
    assert normalize.normalize_property_type("Detached House") == "DETACHED"
    assert normalize.normalize_property_type("Strata Terrace") == "STRATA_TERRACE"


def test_area_range_and_band():
    assert normalize.parse_area_range("1500-2000") == (1500.0, 2000.0, 1750.0)
    assert normalize.area_band("TERRACE", 1750) == "1500-2000"
    assert normalize.area_band("SEMI_D", 4000) == "3500-5000"


def test_extract_street():
    assert normalize.extract_street("15 NASSIM ROAD,17 NASSIM ROAD") == "NASSIM ROAD"
    assert normalize.extract_street("230 VICTORIA STREET, BUGIS JUNCTION") == "VICTORIA STREET"
