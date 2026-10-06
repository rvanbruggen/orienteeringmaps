from app.suggest import find_survey_date, group_key, parse_filename, suggest


def test_hitta_pdf_text():
    text = "EXPEDITIE HITTA\nMeetshoven 2km\nSchaal 1/7.500\nHoogtelijnen 2m\nDeze omloop is 2km lang en gaat dwars door Meetshoven in Aarschot!\nDe orienteering club\nOMEGA is hier actief!"
    s = suggest("HITTA-Routes-OV-Aarschot-Kort.pdf", text)
    assert s["name"] == "Aarschot"
    assert s["scale"] == 7500
    assert s["contour_interval"] == 2
    assert s["clubs"] == ["OMEGA"]
    assert s["location"] == "Aarschot"
    assert s["course"] == {"name": "Kort", "scale": 7500, "length_km": 2.0}
    assert "HITTA" in s["tags"] and s["map_type"] == "permanent"


def test_mapico_header():
    text = "Brielmeersen\nDeinze\nSCHAAL 1/3.000\nHOOGTE 2 meter\nKAART Mei 2021\nTEKENING Jeremy Genar\nLEGENDE"
    s = suggest("Mapico Brielmeersen Kaart.pdf", text, page_count=28)
    assert (s["scale"], s["contour_interval"], s["survey_date"]) == (3000, 2, "2021-05")
    assert s["cartographer"] == "Jeremy Genar"
    assert s["multi_page"] is True


def test_scale_split_over_lines_and_multiple_clubs():
    s = suggest("x.pdf", "Schaal\n1/4.000\nDe orienteering clubs\nHamok en OMEGA zijn hier actief!")
    assert s["scale"] == 4000
    assert s["clubs"] == ["Hamok", "OMEGA"]


def test_survey_dates():
    assert find_survey_date("Survey: 2019") == "2019"
    assert find_survey_date("kartering 03/2015") == "2015-03"
    assert find_survey_date("Kaart 12/04/2022") == "2022-04-12"
    assert find_survey_date("KAART Mei 2021") == "2021-05"
    assert find_survey_date("Kaart: 12 april 2022") == "2022-04-12"


def test_filenames():
    assert parse_filename("HandleidingMapicoGuldenKamer.pdf")["name"] == "Gulden Kamer"
    assert parse_filename("Baanlegging SiG_all.Boggle 3.1.pdf")["label"] == "3.1"
    assert group_key("HITTA-Routes-OV-Leuven-Kort.pdf") == group_key("HITTA-Routes-OV-Leuven-Lang.pdf")
    assert suggest("HandleidingMapicoGuldenKamer.pdf", "")["kind"] == "manual"
