"""Все ниши в niches/: конфиг валиден, у мастеров только существующие услуги, графики разбираются.
Добавили свою нишу — этот тест сразу покажет опечатку."""

import pytest
import yaml

from booking.config import ROOT
from booking.niche import Niche
from booking.services.seed import parse_schedule

NICHES = sorted(p.name for p in (ROOT / "niches").iterdir() if p.is_dir())


@pytest.mark.parametrize("name", NICHES)
def test_niche(name):
    folder = ROOT / "niches" / name
    Niche.model_validate(yaml.safe_load((folder / "config.yaml").read_text(encoding="utf-8")))
    catalog = yaml.safe_load((folder / "catalog.yaml").read_text(encoding="utf-8"))
    branches = {b["slug"] for b in catalog["branches"]}
    services = {s["slug"] for s in catalog["services"]}
    assert len(services) == len(catalog["services"]), "повторяющийся slug услуги"
    offered = set()
    for m in catalog["masters"]:
        assert m.get("branch", next(iter(branches))) in branches, f"{m['slug']}: нет филиала"
        own = set(m["services"])
        assert own <= services, f"{m['slug']}: нет услуг {own - services}"
        offered |= own
        rules = parse_schedule(m["schedule"])
        assert rules and all(a < b for _, a, b in rules), f"{m['slug']}: пустой или неверный график"
    assert offered == services, f"услуги без мастеров: {services - offered}"
