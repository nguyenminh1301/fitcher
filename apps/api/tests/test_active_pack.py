"""Which pack the instance answers from: ACTIVE_PACK when set, else the one the app state records."""

from state_fixtures import new_state

from app.packs.active import active_pack, set_active_pack


def test_without_either_there_is_no_active_pack(tmp_path):
    db, _ = new_state(tmp_path)

    assert active_pack(db, env={}) == ""


def test_the_app_state_names_the_pack_an_instant_pack_made_active(tmp_path):
    db, _ = new_state(tmp_path)

    set_active_pack(db, "shop")

    assert active_pack(db, env={}) == "shop"


def test_the_environment_wins_over_the_app_state(tmp_path):
    db, _ = new_state(tmp_path)
    set_active_pack(db, "shop")

    assert active_pack(db, env={"ACTIVE_PACK": "fixed"}) == "fixed"
