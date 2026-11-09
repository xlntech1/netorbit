"""Tests for the pure settings helpers in manage.py: free text fields and made-up hub names."""

import pytest

from custom_components.netorbit import manage


def _opts():
    return {"hubs": [{"id": "gateway", "name": "Router", "parent": None, "type": "router"}], "devices": {}, "ignored": [], "dismissed_hubs": []}


def test_set_fields_merges_trims_and_removes():
    cfg = {}
    manage.set_fields(cfg, " https://192.0.2.1/ ", {" Location ": " Hall  closet ", "Owner": "Sam"})
    assert cfg == {"managed_by": "https://192.0.2.1/", "fields": {"Location": "Hall closet", "Owner": "Sam"}}
    # None leaves managed_by alone; an empty value drops a label; a new label is added.
    manage.set_fields(cfg, None, {"Owner": None, "Serial": "ABC", "": "ignored"})
    assert cfg == {"managed_by": "https://192.0.2.1/", "fields": {"Location": "Hall closet", "Serial": "ABC"}}
    # An empty managed_by removes it; removing the last field removes the key.
    manage.set_fields(cfg, "", {"Location": "", "Serial": None})
    assert cfg == {}


def test_set_fields_limits():
    cfg = {}
    with pytest.raises(manage.ManageError):
        manage.set_fields(cfg, None, {"x" * 41: "v"})
    with pytest.raises(manage.ManageError):
        manage.set_fields(cfg, None, {"Notes": "v" * 501})
    with pytest.raises(manage.ManageError):
        manage.set_fields(cfg, "m" * 501, None)
    with pytest.raises(manage.ManageError):
        manage.set_fields(cfg, None, {f"f{i}": "v" for i in range(21)})
    with pytest.raises(manage.ManageError):
        manage.set_fields(cfg, None, ["not", "a", "mapping"])
    assert cfg == {}


def test_stored_text_leaves_out_what_is_not_text():
    assert manage.stored_text({"managed_by": "ISP", "fields": {"Rack": "2"}}) == {"managed_by": "ISP", "fields": {"Rack": "2"}}
    assert manage.stored_text({"managed_by": 5, "fields": "abc"}) == {"managed_by": None, "fields": {}}
    assert manage.stored_text({"fields": {"Rack": 2, "Notes": "spare"}}) == {"managed_by": None, "fields": {"Notes": "spare"}}
    # A broken saved value doesn't stop the next edit, which replaces it.
    cfg = {"fields": "abc"}
    manage.set_fields(cfg, None, {"Rack": "2"})
    assert cfg == {"fields": {"Rack": "2"}}
    assert manage.fields_to_text("abc") == ""


def test_parse_fields_text_round_trip():
    text = "Location: Hall\nURL: https://192.0.2.1/admin\n\nEmpty:"
    fields = manage.parse_fields_text(text)
    assert fields == {"Location": "Hall", "URL": "https://192.0.2.1/admin", "Empty": ""}
    assert manage.fields_to_text({"Location": "Hall", "URL": "https://192.0.2.1/admin"}) == "Location: Hall\nURL: https://192.0.2.1/admin"
    assert manage.parse_fields_text(None) == {} and manage.fields_to_text(None) == ""
    with pytest.raises(manage.ManageError):
        manage.parse_fields_text("no separator here")
    with pytest.raises(manage.ManageError):
        manage.parse_fields_text(": value without a label")


def test_hub_names_made_up_or_chosen():
    opts = _opts()
    auto = manage.add_hub(opts, "Acme switch 53:0B", "switch", None, "192.0.2.5", None, source="snmp")
    chosen = manage.add_hub(opts, "Hallway AP", "access_point", None, "192.0.2.6", None, source="manual")
    guessed = manage.add_hub(opts, "Attic AP", "access_point", None, "192.0.2.7", None, source="manual", name_auto=True)
    by_id = {h["id"]: h for h in opts["hubs"]}
    assert by_id[auto["hub"]]["name_auto"] is True
    assert by_id[chosen["hub"]]["name_auto"] is False
    assert by_id[guessed["hub"]]["name_auto"] is True
    # Renaming is a choice; changing the type alone is not.
    manage.update_hub(opts, guessed["hub"], type="mesh_node")
    assert by_id[guessed["hub"]]["name_auto"] is True
    manage.update_hub(opts, guessed["hub"], name="Loft AP")
    assert by_id[guessed["hub"]]["name"] == "Loft AP" and by_id[guessed["hub"]]["name_auto"] is False
    # Free text on hubs goes through the same rules.
    manage.update_hub(opts, chosen["hub"], managed_by="Router", fields={"Rack": "2"})
    assert by_id[chosen["hub"]]["managed_by"] == "Router" and by_id[chosen["hub"]]["fields"] == {"Rack": "2"}
