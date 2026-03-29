"""save_parser.py — Paradox Script gamestate reader (tested against Phoenix v4.x)."""

import re
import sys
import zipfile
from pathlib import Path

_NAME_NOISE = {
    "adjective",
    "article",
    "prefix",
    "suffix",
    "noun",
    "plural",
    "value",
    "key",
}
_SKIP_TOP_KEYS = {"AassocB", "AofB", "AassocOfB", "AofBwithC"}
_SKIP_DESCRIPTORS = {
    "Society_Name",
    "Civilization",
    "Civilization_Name",
    "Culture_Name",
    "Empire",
    "Kingdom",
    "Republic",
    "Hegemony",
    "Dominion",
    "Confederation",
    "Sovereignty",
    "Collective",
    "Syndicate",
    "Directorate",
    "Imperium",
}

_FALLEN_EMPIRE_MIL_THRESHOLD = 5000

NOTABLE_TECH_LABELS = {
    "tech_destroyers": "Destroyers",
    "tech_cruisers": "Cruisers",
    "tech_battleships": "Battleships",
    "tech_titans": "Titans",
    "tech_juggernaut": "Juggernaut",
    "tech_colossus": "Colossus",
    "tech_world_cracker": "World Cracker",
    "tech_global_pacifier": "Global Pacifier",
    "tech_neutron_sweep": "Neutron Sweep",
    "tech_nanobot_diffuser": "Nanobot Diffuser",
    "tech_divine_enforcer": "Divine Enforcer",
    "tech_armageddon_bombardment": "Armageddon Bombardment",
    "tech_mega_engineering": "Mega-Engineering",
    "tech_dyson_sphere": "Dyson Sphere",
    "tech_ring_world": "Ring World",
    "tech_matter_decompressor": "Matter Decompressor",
    "tech_mega_art_installation": "Mega Art Installation",
    "tech_strategic_coordination": "Strategic Coordination Center",
    "tech_interstellar_assembly": "Interstellar Assembly",
    "tech_mega_shipyard": "Mega Shipyard",
    "tech_spy_orb": "Spy Orb",
    "tech_orbital_habitat": "Orbital Habitats",
    "tech_gateway_activation": "Gateway Activation",
    "tech_gateway_construction": "Gateway Construction",
    "tech_psionic_theory": "Psionic Theory",
    "tech_mind_over_matter": "Mind Over Matter",
    "tech_transcendence": "Transcendence",
    "tech_covenant_eater_of_worlds": "Covenant: Eater of Worlds",
    "tech_covenant_instrument_of_desire": "Covenant: Instrument of Desire",
    "tech_covenant_composer_of_strands": "Covenant: Composer of Strands",
    "tech_covenant_whispers_in_the_void": "Covenant: Whispers in the Void",
    "tech_synthetic_workers": "Synthetic Workers",
    "tech_synthetic_leaders": "Synthetic Leaders",
    "tech_synthetic_evolution": "Synthetic Evolution (The Flesh is Weak)",
    "tech_gene_tailoring": "Gene Tailoring",
    "tech_engineered_evolution": "Engineered Evolution",
    "tech_evolutionary_mastery": "Evolutionary Mastery",
    "tech_jump_drive_1": "Jump Drive",
    "tech_psi_jump_drive_1": "Psi Jump Drive",
    "tech_wormhole_stabilization": "Wormhole Stabilization",
    "tech_epigenetic_triggers": "Epigenetic Triggers",
    "tech_galactic_administration": "Galactic Administration",
    "tech_galactic_bureaucracy": "Advanced Bureaucracy",
    "tech_neural_implants": "Neural Implants",
    "tech_autonomous_agents": "Autonomous Agents",
    "tech_sapient_ai": "Sapient AI",
    "tech_positronic_implants": "Positronic Implants",
    "tech_climate_restoration": "Climate Restoration",
    "tech_terraforming": "Terraforming",
    "tech_selected_lineages": "Selected Lineages",
    "tech_eugenics": "Eugenics",
    "tech_extradimensional_weapon": "Dimensional Weaponry",
    "tech_dark_matter_propulsion": "Dark Matter Propulsion",
    "tech_dark_matter_power_core": "Dark Matter Power Core",
    "tech_dark_matter_deflector": "Dark Matter Deflector",
    "tech_nano_vitality_crop": "Nano-Vitality Crops",
}


def load_gamestate(sav_path: str) -> str:
    with zipfile.ZipFile(sav_path, "r") as z:
        raw = z.read("gamestate")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def peek_date(sav_path: str) -> str | None:
    try:
        with zipfile.ZipFile(sav_path, "r") as z:
            with z.open("gamestate") as f:
                chunk = f.read(4096)
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            text = chunk.decode("latin-1")
        m = re.search(r'(?:^|\n)date\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else None
    except Exception:
        return None


def _detect_ironman(gs: str) -> bool:
    match = re.search(r"(?:^|\n)ironman\s*=\s*yes", gs[:4096])
    return match is not None


def _index_blocks(text: str) -> dict[str, int]:
    idx: dict[str, int] = {}
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        if c in " \t\r\n":
            i += 1
            continue

        if c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue

        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 1
            i += 1
            continue

        if c in "{}":
            i += 1
            continue

        j = i
        while j < n and text[j] not in ' \t\r\n=#{}"':
            j += 1
        if j == i:
            i += 1
            continue
        key = text[i:j]
        i = j

        while i < n and text[i] in " \t":
            i += 1
        if i >= n or text[i] != "=":
            while i < n and text[i] != "\n":
                i += 1
            continue
        i += 1

        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break

        if text[i] == "{":
            i += 1
            if key not in idx:
                idx[key] = i
            depth = 1
            while i < n and depth > 0:
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                elif ch == '"':
                    i += 1
                    while i < n and text[i] != '"':
                        i += 1
                i += 1
        else:
            while i < n and text[i] not in "\r\n":
                i += 1

    return idx


def _extract_block(text: str, start: int) -> str:
    depth, i = 1, start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start : i - 1]


def _named_block(text: str, key: str) -> str:
    m = re.search(rf"(?:^|\n)\s*{re.escape(key)}\s*=\s*\{{", text)
    return _extract_block(text, m.end()) if m else ""


def _reconstruct_name(name_blk: str) -> str | None:
    if re.search(r"literal\s*=\s*yes", name_blk):
        m = re.search(r'(?:^|\n)\s*key\s*=\s*"([^"]+)"', name_blk)
        return m.group(1) if m else None

    all_keys = re.findall(r'key\s*=\s*"([^"]+)"', name_blk)
    if not all_keys:
        return None
    top_key = all_keys[0]

    if (top_key.startswith("NAME_") or top_key.startswith("EMPIRE_")) and len(
        all_keys
    ) == 1:
        return top_key[top_key.index("_") + 1 :].replace("_", " ").title()

    if top_key in _SKIP_TOP_KEYS:
        return None

    spec_keys = []
    for k in all_keys:
        if k.startswith("SPEC_"):
            spec_keys.append(k[5:])
        elif k.startswith("NAME_") or k.startswith("EMPIRE_"):
            spec_keys.append(k[k.index("_") + 1 :].replace("_", " "))
        elif k.startswith("PRESCRIPTED_"):
            parts = [
                p
                for p in k.split("_")
                if p.lower() not in ("prescripted", "species", "name", "adj", "plural")
            ]
            if parts:
                spec_keys.append(" ".join(parts))

    plain_keys = [
        k.replace("_", " ")
        for k in all_keys
        if not k.startswith("%")
        and not k.startswith("SPEC_")
        and not k.startswith("NAME_")
        and k.lower() not in _NAME_NOISE
        and not re.fullmatch(r"\d+", k)
        and k not in _SKIP_DESCRIPTORS
    ]

    non_noise = [
        k
        for k in all_keys
        if not k.startswith("%")
        and not re.fullmatch(r"\d+", k)
        and k.lower() not in _NAME_NOISE
    ]
    if not plain_keys and all(
        k in _SKIP_DESCRIPTORS
        or k.startswith("SPEC_")
        or k.startswith("NAME_")
        or k.startswith("EMPIRE_")
        for k in non_noise
    ):
        return " ".join(spec_keys) if spec_keys else None

    seen: set = set()
    unique = []
    for p in spec_keys + plain_keys:
        if p.lower() not in seen:
            seen.add(p.lower())
            unique.append(p)
    name = " ".join(unique) if unique else None
    return name.title() if name else None


def _build_species_map(db_blk: str, db_idx: dict) -> dict:
    species_map: dict = {}
    for tag, pos in db_idx.items():
        if not tag.isdigit():
            continue
        blk = _extract_block(db_blk, pos)
        name_blk = _named_block(blk, "name")
        key_m = (
            re.search(r'(?:^|\n)\s*key\s*=\s*"([^"]+)"', name_blk) if name_blk else None
        )
        if key_m:
            raw = key_m.group(1)
            if raw.startswith("SPEC_"):
                species_map[tag] = raw[5:].title()
            elif raw.startswith("NAME_") or raw.startswith("EMPIRE_"):
                species_map[tag] = raw[raw.index("_") + 1 :].replace("_", " ").title()
            elif raw.startswith("PRESCRIPTED_"):
                parts = [
                    p
                    for p in raw.split("_")
                    if p.lower()
                    not in ("prescripted", "species", "name", "adj", "plural")
                ]
                species_map[tag] = " ".join(parts).title() if parts else raw
            else:
                species_map[tag] = raw
    return species_map


def _parse_owned_planet_count(blk: str) -> int:
    m = re.search(r"owned_planets\s*=\s*\{([^}]*)\}", blk)
    if not m:
        return 0
    return len(re.findall(r"\d+", m.group(1)))


def _parse_notable_techs(blk: str) -> list[str]:
    ts_blk = _named_block(blk, "tech_status")
    if not ts_blk:
        return []
    t_m = re.search(r"technology\s*=\s*\{", ts_blk)
    if not t_m:
        return []
    technology_blk = _extract_block(ts_blk, t_m.end())
    tech_keys = re.findall(r'"([^"]+)"', technology_blk)
    return [NOTABLE_TECH_LABELS[k] for k in tech_keys if k in NOTABLE_TECH_LABELS]


def _parse_country(blk: str, tag: str, species_map: dict) -> dict | None:
    name = _reconstruct_name(_named_block(blk, "name"))
    if not name:
        return None

    ethos_blk = _named_block(blk, "ethos")
    ethics = re.findall(r'ethic\s*=\s*"([^"]+)"', ethos_blk)

    gov_blk = _named_block(blk, "government")
    auth_m = re.search(r'authority\s*=\s*"([^"]+)"', gov_blk) if gov_blk else None
    authority = auth_m.group(1) if auth_m else ""
    civics_blk = _named_block(gov_blk, "civics") if gov_blk else ""
    civics = re.findall(r'"(civic_[^"]+)"', civics_blk)

    ref_m = re.search(r"species_ref\s*=\s*(\d+)", blk)
    species = (
        species_map.get(ref_m.group(1), "unknown species")
        if ref_m
        else "unknown species"
    )

    mil_m = re.search(r"military_power\s*=\s*([\d.]+)", blk)
    military = float(mil_m.group(1)) if mil_m else 0.0

    planets = _parse_owned_planet_count(blk)
    techs = _parse_notable_techs(blk)

    return {
        "name": name,
        "tag": tag,
        "ethics": ethics,
        "civics": civics,
        "authority": authority,
        "species": species,
        "military": int(military),
        "planets": planets,
        "techs": techs,
    }


def parse_save(sav_path: str) -> dict:
    gs = load_gamestate(sav_path)

    top_idx = _index_blocks(gs)

    date_m = re.search(r'(?:^|\n)date\s*=\s*"([^"]+)"', gs[:2048])
    date = date_m.group(1) if date_m else "???"
    pm = re.search(r"player\s*=\s*\{[^}]*country\s*=\s*(\d+)", gs, re.DOTALL)
    player_tag = pm.group(1) if pm else "0"

    ironman = _detect_ironman(gs)

    species_map: dict = {}
    if "species_db" in top_idx:
        db_blk = _extract_block(gs, top_idx["species_db"])
        db_idx = _index_blocks(db_blk)
        species_map = _build_species_map(db_blk, db_idx)

    if "country" not in top_idx:
        print("WARNING: 'country' block not found in gamestate.", file=sys.stderr)
        return {
            "date": date,
            "player": {},
            "empires": [],
            "met_tags": set(),
            "path": sav_path,
            "ironman": ironman,
        }

    country_blk = _extract_block(gs, top_idx["country"])
    country_idx = _index_blocks(country_blk)

    all_tags = [k for k in country_idx if k.isdigit()]

    player_blk = (
        _extract_block(country_blk, country_idx[player_tag])
        if player_tag in country_idx
        else ""
    )
    player = _parse_country(player_blk, player_tag, species_map) or {}

    top_name_m = re.search(r'\nname\s*=\s*"([^"]+)"', gs[:4096])
    if top_name_m:
        player["name"] = top_name_m.group(1)
    if not player.get("name"):
        player["name"] = "Your Empire"

    empires: list = []
    for tag in all_tags:
        if tag == player_tag:
            continue
        blk = _extract_block(country_blk, country_idx[tag])
        e = _parse_country(blk, tag, species_map)
        if not e or not e["ethics"]:
            continue
        if float(e["military"]) > _FALLEN_EMPIRE_MIL_THRESHOLD:
            continue
        empires.append(e)
        if len(empires) >= 32:
            break

    try:
        game_year = int(date.split(".")[0])
    except Exception:
        game_year = 2200

    relation_met = set()
    for m in re.finditer(r"relation\s*=\s*\{([^}]+)\}", player_blk):
        blk = m.group(1)
        if "contact=yes" in blk:
            cm = re.search(r"country\s*=\s*(\d+)", blk)
            if cm:
                relation_met.add(cm.group(1))

    enclave_tags = {e["tag"] for e in empires if float(e.get("military", 0)) == 0}

    if game_year <= 2200 and not relation_met:
        met_tags = enclave_tags.copy()
    elif game_year >= 2215 and not relation_met:
        met_tags = {e["tag"] for e in empires}
    else:
        met_tags = relation_met | enclave_tags

    return {
        "date": date,
        "player": player,
        "empires": empires,
        "met_tags": met_tags,
        "path": sav_path,
        "ironman": ironman,
    }


def newest_save(save_dir: str) -> str | None:
    p = Path(save_dir)
    if not p.exists():
        return None
    saves = list(p.rglob("*.sav"))
    if not saves:
        return None
    return str(max(saves, key=lambda f: f.stat().st_mtime))
