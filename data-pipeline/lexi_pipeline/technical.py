"""Technical vocabulary deck (engineering / CS / science students).

Candidates come only from open data:
  * WordNet topic domains (explicit "computer science", "physics", … labels),
  * Wiktionary sense labels ("computing: input device") from WikDict,
  * WordNet hyponyms of a short list of technical root concepts — only when that
    sense is the word's *primary* sense, so "clock" (instrument) is accepted but
    "hip" (a roof part) is not.
Words must be common enough to be useful (wordfreq Zipf ≥ MIN_ZIPF). Levels come
from the CEFR lists when the word is there, otherwise they are estimated from
frequency with thresholds calibrated on the CEFR lists (``level_source="frequency"``).
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Callable, Iterable

from .cefr import make_id
from .models import LEVELS, POS_TO_WN, QUALITY, Definition, Entry, level_index
from .text import clean_gloss, leaks, tokens

Zipf = Callable[[str], float]

# field id -> ru title, WordNet topic-domain roots (+ hyponyms), technical root
# concepts (+ hyponyms, primary senses only), Wiktionary labels.
FIELDS: dict[str, dict] = {
    "it": {
        "title": "ИТ",
        "topics": ["computer_science.n.01", "computer.n.01", "telecommunication.n.01"],
        "roots": ["computer.n.01", "software.n.01", "computer_memory.n.01", "computer_network.n.01",
                  "peripheral.n.01", "program.n.07", "code.n.03", "computer_file.n.01",
                  "operating_system.n.01", "algorithm.n.01", "data_structure.n.01", "programming_language.n.01",
                  "memory_device.n.01", "computer_memory_unit.n.01", "instruction.n.04", "computer_circuit.n.01",
                  "function.n.07", "web_site.n.01", "code.n.02"],
        "broad_roots": ["database.n.01"],
        "labels": ["computing", "programming", "computer science", "internet", "software", "networking",
                   "telecommunications", "computer"],
    },
    "electrical": {
        "title": "Электротехника",
        "topics": ["electronics.n.01", "electricity.n.01"],
        "roots": ["electronic_device.n.01", "circuit.n.01", "electronic_equipment.n.01",
                  "semiconductor_device.n.01", "electricity.n.01", "battery.n.02", "conductor.n.04",
                  "electrical_device.n.01", "transducer.n.01", "electrode.n.01", "semiconductor.n.01", "magnet.n.01",
                  "antenna.n.01", "electric_motor.n.01", "generator.n.02", "transformer.n.01", "wire.n.02",
                  "resistor.n.01", "capacitor.n.01", "current_unit.n.01", "potential_unit.n.01",
                  "resistance_unit.n.01", "capacitance_unit.n.01", "power_unit.n.01"],
        "labels": ["electronics", "electricity", "electrical engineering", "electrical"],
    },
    "physics": {
        "title": "Физика",
        "topics": ["physics.n.01"],
        "roots": ["energy.n.01", "force.n.02", "radiation.n.01", "elementary_particle.n.01",
                  "physical_property.n.01", "electromagnetic_radiation.n.01", "subatomic_particle.n.01",
                  "optical_device.n.01", "lens.n.01", "work_unit.n.01", "force_unit.n.01", "pressure_unit.n.01",
                  "temperature_unit.n.01"],
        "broad_roots": ["physical_phenomenon.n.01"],
        "labels": ["physics", "optics", "mechanics", "thermodynamics", "nuclear physics"],
    },
    "math": {
        "title": "Математика",
        "topics": ["mathematics.n.01"],
        "roots": ["mathematical_relation.n.01", "plane_figure.n.01", "solid.n.03", "equation.n.01",
                  "matrix.n.01", "calculation.n.02", "mathematical_function.n.01", "curve.n.01", "angle.n.01",
                  "figure.n.06", "statistic.n.01", "mathematical_operation.n.01", "set.n.02", "line.n.04"],
        "broad_roots": ["number.n.02"],
        "labels": ["mathematics", "math", "geometry", "arithmetic", "algebra", "statistics", "set theory",
                   "calculus", "trigonometry", "topology"],
    },
    "chemistry": {
        "title": "Химия",
        "topics": ["chemistry.n.01"],
        "roots": ["chemical_element.n.01", "chemical_reaction.n.01", "chemical_bond.n.01", "atom.n.01",
                  "ion.n.01", "acid.n.01", "molecule.n.01", "chemical_process.n.01", "isotope.n.01", "polymer.n.01",
                  "catalyst.n.01", "oxide.n.01", "salt.n.01", "alkali.n.01", "solution.n.01"],
        "broad_roots": ["compound.n.02", "gas.n.02"],
        "labels": ["chemistry", "organic chemistry", "inorganic chemistry", "biochemistry"],
    },
    "engineering": {
        "title": "Инженерия",
        "topics": ["engineering.n.02", "metallurgy.n.01", "mechanics.n.01"],
        "roots": ["machine.n.01", "engine.n.01", "motor.n.01", "measuring_instrument.n.01",
                  "mechanical_device.n.01", "power_tool.n.01", "gear.n.01", "valve.n.03", "pump.n.01",
                  "alloy.n.01", "metal.n.01", "building_material.n.01", "structural_member.n.01",
                  "unit_of_measurement.n.01", "mechanism.n.05", "bearing.n.06", "spring.n.02", "lever.n.01",
                  "pipe.n.02", "rocket.n.01", "beam.n.02", "apparatus.n.01", "machinery.n.01"],
        "broad_roots": ["fastener.n.02", "aircraft.n.01"],
        "labels": ["engineering", "mechanical engineering", "construction", "metallurgy"],
    },
}
# Subtrees that sit under a technical root but are everyday or off-topic.
EXCLUDED_ROOTS = ["monetary_unit.n.01", "time_unit.n.01", "atmospheric_phenomenon.n.01",
                  "weather.n.01", "garden_tool.n.01", "kitchen_utensil.n.01", "cutter.n.06",
                  "home_appliance.n.01", "lamp.n.01", "timepiece.n.01", "musical_instrument.n.01",
                  "weapon.n.01", "sound.n.04", "taste_property.n.01", "visual_property.n.01",
                  "concave_shape.n.01", "convex_shape.n.01", "farm_machine.n.01", "avoirdupois_unit.n.01",
                  "area_unit.n.01", "british_capacity_unit.n.01", "united_states_liquid_unit.n.01",
                  "united_states_dry_unit.n.01", "apothecaries'_unit.n.01", "troy_unit.n.01",
                  "nautical_linear_unit.n.01", "recording.n.03", "breath.n.02", "animal_oil.n.01",
                  "covering_material.n.01", "stone.n.02", "textile_machine.n.01", "digit.n.01", "large_integer.n.01",
                  "enzyme.n.01", "natural_resin.n.01", "hand_tool.n.01", "sports_equipment.n.01",
                  "toiletry.n.01", "foodstuff.n.02", "beverage.n.01", "drug.n.01", "cosmetic.n.01"]
# Reviewed by hand: words that pass the rules but are not useful technical vocabulary
# (everyday senses, slang, archaic units). Keep this list short and documented.
STOPLIST = {
    "cool", "hit", "twain", "crore", "gill", "puberty", "spell", "stone", "grand", "dozen", "score",
    "gross", "hand", "span", "pinch", "dash", "peck", "include", "give", "blaze", "haze", "starlight",
    "rut", "incision", "chop", "render", "harrow", "pitchfork", "growing", "activity", "foot", "pencil",
    "primary", "yard", "grab", "reform", "seek", "timetable", "network:verb", "henry", "lynx", "docket",
    "discography", "credits", "inventory", "alphabet", "candlelight", "invisibility", "heft", "agonist",
    "jukebox", "brimstone", "quarter", "flavor", "absorb", "sunbeam", "moonbeam", "pounder", "perversion",
    "scallop", "halitosis", "blubber", "gavel",
    # second review after widening the roots: everyday objects, food, art, obscure or archaic units
    "dildo", "faggot", "kamikaze", "welterweight", "birdie", "carousel", "cameo", "carving", "sculpture",
    "statue", "rainbow", "belt", "maypole", "trapeze", "goalpost", "lamppost", "doorbell", "hairpin",
    "barrette", "curler", "nutcracker", "skewer", "frail", "catty", "kos", "hin", "oka", "tod", "cran", "lea",
    "vara", "dol", "cicero", "ligne", "cubit", "rundle", "lally", "peavey", "yarder", "jimmy", "moonshine",
    "snuff", "gargle", "suet", "lard", "drippings", "jaggery", "demerara", "sago", "cassava", "manna",
    "lemongrass", "incense", "attar", "arum", "cutch", "bilge", "slush", "marbling", "shortening", "hypo",
    "monad", "rennet", "chill", "coma", "dip", "jerk", "limb", "mist", "simmer", "sunglass", "sunburst",
    "monocle", "firelight", "gaslight", "torchlight", "moonlight", "obviousness", "heaviness", "hotness",
    "shortness", "canal", "bibliography", "playbill", "masthead", "codex", "contents", "checklist",
    "blacklist", "google", "telecast", "arch", "bend", "bight", "brink", "circlet", "herm", "rouleau",
    "roulette", "rim", "periphery", "par", "quota", "moiety", "guesstimate", "pagination", "meander",
    "airbus", "bomber", "warplane", "interceptor", "maypole", "sill", "stile", "thwart", "workhorse",
    "upright", "footer", "slipknot", "zapper", "tannoy", "bullhorn", "beeper", "echo", "envelope", "stereo",
    "mono", "sabin", "sone", "phon", "phot", "nit", "lambert", "langley", "gilbert", "poise", "denier",
    "quintal", "furlong", "fathom", "carat", "karat", "megaton", "miler", "egress", "ingress", "epoch",
    "event", "spam", "playlist", "replay", "television", "video", "streaming", "faceplate", "chert",
    "flintstone", "firestone", "alabaster", "beeswax", "cornstarch", "meltwater", "napalm", "digitalis",
    "cartwheel", "dredge", "colter", "calender", "shingle", "clapboard", "planking", "lumber", "sawmill",
    "windowsill", "sewer", "sink", "faucet", "sprinkler", "padlock", "buckle", "clasp", "frail", "helm",
    "android", "dropper", "integrator", "pole", "portable", "android",
}
# Core terms from first-year university courses, reviewed by hand. The rules above find
# terms by WordNet structure; these make sure the essential vocabulary of each field is
# present even when WordNet files it elsewhere ("velocity" is a rate, "kernel" a seed).
# "word" = noun, "word:a"/"word:v" = adjective/verb, "word=synset" pins the sense.
SEEDS: dict[str, str] = {
    "it": """algorithm compiler debugger interpreter encryption decryption bandwidth router protocol firmware
        cache bitmap pixel binary=binary.n.02 browser=browser.n.02 server database byte kilobyte megabyte
        gigabyte terabyte modem cursor software hardware spreadsheet subroutine iteration recursion compile:v
        debug:v encode:v decode:v download:v upload:v hyperlink hypertext password firewall backup reboot:v
        buffer=buffer.n.04 packet bus=bus.n.02 interface=interface.n.02 mainframe microprocessor workstation
        programmer programming parse:v parser metadata multiplexer cybernetics automation robotics digitize:v
        scanner=scanner.n.02 bug=bug.n.02 virus=virus.n.03 spyware freeware shareware directory=directory.n.02
        checksum datum keyboard joystick megahertz gigahertz computation=computation.n.01""",
    "electrical": """transistor diode=diode.n.02 oscilloscope voltmeter ammeter galvanometer rectifier amplifier
        thermistor solenoid relay=relay.n.05 impedance inductance=inductance.n.01 capacitance=capacitance.n.01
        conductance transformer insulator=insulator.n.01 conductor=conductor.n.04 semiconductor
        circuit=circuit.n.01 voltage ampere=ampere.n.02 volt ohm watt farad coulomb electrode anode cathode
        fuse=fuse.n.01 cable=cable.n.02 battery=battery.n.02 generator=generator.n.02 dynamo armature
        coil=coil.n.06 wattage amperage potentiometer rheostat electromagnet photocell transducer sensor
        antenna electromagnetism kilowatt megawatt milliampere kilovolt switchboard socket=socket.n.03
        plug=plug.n.05 wiring circuitry electrician electrification electrify:v""",
    "physics": """momentum inertia friction acceleration velocity torque entropy wavelength=wavelength.n.01
        amplitude refraction diffraction photon neutron electron proton quark viscosity buoyancy=buoyancy.n.03
        gravitation thermodynamics mechanics optics magnetism radioactivity fission fusion=fusion.n.04 quantum
        oscillation resonance spectrum=spectrum.n.01 laser prism=prism.n.02 joule newton=newton.n.02
        pascal=pascal.n.01 kelvin decibel hertz equilibrium elasticity conduction convection=convection.n.01
        plasma=plasma.n.03 nucleus=nucleus.n.02 particle=particle.n.02 kinetic:a neutrino positron hadron
        boson lepton meson isotope luminosity acoustics electrostatics hydrodynamics aerodynamics
        polarization=polarization.n.01""",
    "math": """integral derivative=derivative.n.01 vector=vector.n.01 matrix=matrix.n.01 tensor=tensor.n.01
        polynomial logarithm theorem=theorem.n.01 axiom=axiom.n.02 hypotenuse parabola hyperbola ellipse
        asymptote eigenvalue determinant=determinant.n.03 permutation=permutation.n.02
        probability=probability.n.01 median=median.n.01 quotient=quotient.n.02 dividend=dividend.n.02 divisor
        numerator denominator fraction=fraction.n.03 decimal exponent coefficient constant=constant.n.01
        equation=equation.n.01 subset diameter radius=radius.n.01
        circumference=circumference.n.03 perimeter=perimeter.n.02 angle=angle.n.01 triangle polygon polyhedron
        cube=cube.n.01 sphere=sphere.n.05 cylinder=cylinder.n.02 cone=cone.n.02 pyramid=pyramid.n.01 tangent
        sine cosine cotangent secant=secant.n.02 algebra calculus=calculus.n.03 geometry trigonometry
        arithmetic statistics=statistics.n.01 variance=variance.n.03 histogram axis=axis.n.01 coordinate
        slope=slope.n.02 gradient=gradient.n.01 vertex=vertex.n.01 factorial integer quadrilateral rhombus
        trapezoid parallelogram multiplication division=division.n.11 subtraction addition=addition.n.06
        differentiation=differentiation.n.02 topology""",
    "chemistry": """catalyst electrolyte reduction=reduction.n.02 polymer molecule solvent=solvent.n.01 solute
        isomer alkane alkene reagent valence ester hydrocarbon alkali oxide ion cation anion
        compound=compound.n.02 mixture=mixture.n.01 combustion=combustion.n.01 distillation=distillation.n.01
        filtration=filtration.n.01 evaporation=evaporation.n.01 condensation=condensation.n.02
        crystallization=crystallization.n.01 electrolysis corrosion hydrolysis neutralization=neutralization.n.02
        molarity carbon hydrogen oxygen nitrogen sodium chlorine ammonia methane ethanol benzene glucose
        solubility=solubility.n.01 concentration=concentration.n.01 sublimation=sublimation.n.01 emulsion
        colloid chromatography spectroscopy acid=acid.n.01 salt=salt.n.01 alkaline:a
        acidic:a molecular:a oxidize:v catalysis sulfur phosphorus potassium calcium magnesium
        aluminium=aluminum.n.01 zinc copper iron=iron.n.01 polymerization stoichiometry covalent:a""",
    "engineering": """piston=piston.n.02 crankshaft gearbox lathe bearing=bearing.n.06 alloy weld=weld.n.03 welding
        rivet=rivet.n.02 axle flywheel pneumatic:a actuator chassis=chassis.n.02 girder truss=truss.n.02
        cantilever joist strut=strut.n.02 bolt=bolt.n.06 gear=gear.n.01 cog=cog.n.02 sprocket pulley
        lever=lever.n.01 crank=crank.n.04 camshaft valve=valve.n.03 pump=pump.n.01 boiler=boiler.n.01
        condenser=condenser.n.02 radiator=radiator.n.03 thermostat gasket clutch=clutch.n.06 brake=brake.n.01
        transmission=transmission.n.05 carburetor engine=engine.n.01 propeller rotor=rotor.n.01 drill=drill.n.01
        forging casting=casting.n.01 tolerance=tolerance.n.05 stress=stress.n.05 strain=strain.n.01
        fatigue=fatigue.n.02 concrete=concrete.n.01 steel scaffold=scaffold.n.02 crane=crane.n.04 bulldozer
        conveyor=conveyor.n.02 robot calibration hydraulics pneumatics engineer=engineer.n.01 machinist
        ballast=ballast.n.02""",
}
SEED_MIN_ZIPF = 1.0  # hand-picked terms only need to be real words
MIN_ZIPF = 2.0  # specialised terms are rare in general text (capacitor 2.9, inductor 2.2)
MIN_ESTIMATED_LEVEL = "B1"  # a technical term outside the CEFR lists is never "elementary"
RARE_ZIPF = 4.0  # below this a word is mostly used in its technical sense
MAX_TOPIC_RANK = 3  # the technical sense must be among the word's first senses…
MAX_COMMON_TOPIC_RANK = 2  # …and even earlier for everyday (CEFR A1–B1) words
MAX_LABEL_RANK = 5
STOP_TOKENS = {"a", "an", "the", "of", "or", "and", "to", "in", "by", "that", "for", "with", "on", "as", "is",
               "it", "its", "be", "are", "at", "from", "into", "upon", "which", "who", "whose", "than", "between",
               "other", "another", "more", "most", "one", "two", "any", "some", "such", "not", "no", "each",
               "used", "use", "using", "something", "someone", "thing", "things", "person", "people", "make",
               "made", "having", "has", "have", "part", "especially", "usually", "often", "act", "state",
               "quality", "item", "items", "type", "kind", "form", "way", "very", "much", "many", "also"}
_WORD = re.compile(r"^[a-z]+$")  # single plain words: hyphenated forms are rare and wordfreq overrates them


@dataclass
class TechCandidate:
    lemma: str
    pos: str
    synset: str
    field: str
    via: str  # "seed" | "topic" | "label" | "root"


_FIELD_ORDER = list(FIELDS)


def _closure(wn, names: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for n in names:
        s = wn.synset(n)
        out.add(s.name())
        out.update(x.name() for x in s.closure(lambda t: t.hyponyms() + t.instance_hyponyms()))
    return out


class TechClassifier:
    """Maps a WordNet synset to a technical field (or None)."""

    def __init__(self, wn):
        self.wn = wn
        self.topic_field: dict[str, str] = {}
        self.root_field: dict[str, str] = {}
        # Broad roots (number, chemical compound, tool …) also cover everyday words
        # (dozen, sugar, hammer): they only add words that are not everyday vocabulary.
        self.broad: set[str] = set()
        for fid, spec in FIELDS.items():
            for name in _closure(wn, spec["topics"]):
                self.topic_field.setdefault(name, fid)
            for name in [*spec["roots"], *spec.get("broad_roots", [])]:
                self.root_field.setdefault(name, fid)
            self.broad.update(spec.get("broad_roots", []))
        self.excluded = _closure(wn, EXCLUDED_ROOTS)

    def by_topic(self, synset) -> str | None:
        # NLTK returns related synsets in hash order (it varies between runs): when a sense has
        # several topics ("free" — physics and chemistry), the first field in FIELDS wins.
        found = {self.topic_field[d.name()] for d in synset.topic_domains() if d.name() in self.topic_field}
        return min(found, key=_FIELD_ORDER.index) if found else None

    def by_root(self, synset) -> str | None:
        found = self.root_of(synset)
        return found[0] if found else None

    def root_of(self, synset) -> tuple[str, bool] | None:
        """(field, via a broad root?) — the most specific root wins."""
        if synset.name() in self.excluded:
            return None
        best: tuple[int, int, str, bool] | None = None
        for path in synset.hypernym_paths():
            names = [p.name() for p in path]
            if any(n in self.excluded for n in names):
                return None
            for depth in range(len(names) - 1, -1, -1):
                n = names[depth]
                if n in self.root_field:
                    fid = self.root_field[n]
                    # deepest root; equal depth (paths come in hash order) → the first field in FIELDS
                    cand = (depth, -_FIELD_ORDER.index(fid), fid, n in self.broad)
                    if best is None or cand[:2] > best[:2]:
                        best = cand
                    break
        return (best[2], best[3]) if best else None


_PAREN_LABEL = re.compile(r"^\(([^)]*)\)")


def split_label(gloss: str | None) -> tuple[list[str], str]:
    """'computing: input device' / '(computing) input device' -> (['computing'], 'input device')."""
    if not gloss:
        return [], ""
    m = _PAREN_LABEL.match(gloss.strip())
    if m:
        head, rest = m.group(1), gloss.strip()[m.end():]
    elif ":" in gloss:
        head, rest = gloss.split(":", 1)
    else:
        return [], gloss
    return [l.strip().lower() for l in head.strip("() ").split(",")], rest.strip()


def label_field(gloss: str | None) -> str | None:
    """'computing: input device' -> 'it'."""
    labels, _ = split_label(gloss)
    for fid, spec in FIELDS.items():
        if any(l in spec["labels"] for l in labels):
            return fid
    return None


def acceptable_lemma(lemma: str, zipf: Zipf, pos: str | None = None) -> bool:
    if lemma in STOPLIST or (pos and f"{lemma}:{pos}" in STOPLIST):
        return False
    return bool(_WORD.match(lemma)) and len(lemma) >= 3 and zipf(lemma) >= MIN_ZIPF


_SEED_POS = {"n": "noun", "a": "adjective", "v": "verb"}


def parse_seeds() -> list[tuple[str, str, str, str | None]]:
    """SEEDS -> [(lemma, pos, field, pinned synset or None)], first field wins."""
    out, seen = [], set()
    for fid, text in SEEDS.items():
        for tok in text.split():
            head, _, pinned = tok.partition("=")
            lemma, _, p = head.partition(":")
            key = (lemma, _SEED_POS[p or "n"])
            if key not in seen:
                seen.add(key)
                out.append((*key, fid, pinned or None))
    return out


def resolve_seed(wn, clf: "TechClassifier", lemma: str, pos: str, fid: str, pinned: str | None):
    """The sense a seed term means: the pinned synset, else the first sense the rules place
    in the field, else the first sense whose gloss has a field hint, else the only sense."""
    if pinned:
        try:
            s = wn.synset(pinned)
        except Exception:  # nltk raises WordNetError for unknown names
            return None
        return s if lemma in {l.name().lower() for l in s.lemmas()} else None
    senses = [s for s in wn.synsets(lemma, POS_TO_WN[pos]) if not s.instance_hypernyms()][:6]
    for s in senses:
        if clf.by_topic(s) == fid or clf.by_root(s) == fid:
            return s
    for s in senses:
        if _stems(s.definition()) & FIELD_HINTS[fid]:
            return s
    return senses[0] if len(senses) == 1 else None


def collect_candidates(wn, zipf: Zipf, labelled: dict[tuple[str, str], list] | None = None,
                       common: set[tuple[str, str]] | None = None) -> list[TechCandidate]:
    """One candidate per (lemma, pos); the technical sense with the strongest evidence.
    ``common`` holds everyday (lemma, pos) pairs (CEFR A1–B1)."""
    common = common or set()
    clf = TechClassifier(wn)
    best: dict[tuple[str, str], tuple[int, int, TechCandidate]] = {}
    rank_of_via = {"seed": -1, "topic": 0, "label": 1, "root": 2}

    def offer(lemma: str, pos: str, synset, fid: str, via: str):
        if synset.name() in clf.excluded and via != "seed":
            return
        senses = [x for x in wn.synsets(lemma.replace(" ", "_"), POS_TO_WN[pos]) if not x.instance_hypernyms()]
        try:
            sense_rank = [s.name() for s in senses].index(synset.name())
        except ValueError:
            return
        key = (lemma, pos)
        score = (rank_of_via[via], sense_rank)
        if key not in best or score < best[key][:2]:
            best[key] = (*score, TechCandidate(lemma, pos, synset.name(), fid, via))

    for pos, wn_pos in POS_TO_WN.items():
        if pos == "adverb":
            continue
        for s in wn.all_synsets(wn_pos):
            lemmas = [(i, l) for i, l in enumerate(s.lemmas())
                      if acceptable_lemma(l.name().replace("_", " "), zipf, pos)]
            if not lemmas:
                continue
            topic = clf.by_topic(s)
            found = None if topic else clf.root_of(s)
            root, broad = found if found else (None, False)
            if not topic and not root:
                continue
            for i, l in lemmas:
                lemma = l.name().replace("_", " ")
                senses = [x for x in wn.synsets(l.name(), wn_pos) if not x.instance_hypernyms()]
                rank = next((k for k, x in enumerate(senses) if x == s), 99)
                max_rank = MAX_COMMON_TOPIC_RANK if (lemma, pos) in common else MAX_TOPIC_RANK
                if topic and i == 0 and (rank <= max_rank or (lemma, pos) not in common and zipf(lemma) < RARE_ZIPF):
                    offer(lemma, pos, s, topic, "topic")
                elif root and i == 0 and rank == 0 and not (broad and (lemma, pos) in common):
                    offer(lemma, pos, s, root, "root")
    # Wiktionary labels confirm technical WordNet senses that the rules above skip
    # (e.g. a secondary sense under a technical root). They never add a sense alone.
    for (lemma, pos), senses in (labelled or {}).items():
        if pos == "adverb" or not acceptable_lemma(lemma, zipf, pos):
            continue
        for sense in senses:
            fid = label_field(sense.gloss)
            if not fid:
                continue
            ref = set(tokens(split_label(sense.gloss)[1])) - STOP_TOKENS
            wn_senses = wn.synsets(lemma.replace(" ", "_"), POS_TO_WN[pos])[: MAX_LABEL_RANK + 1]
            scored = [(len(ref & set(tokens(s.definition()))), -i, s) for i, s in enumerate(wn_senses)
                      if clf.by_topic(s) or clf.by_root(s)]
            scored = [x for x in scored if x[0] > 0]
            if scored:
                offer(lemma, pos, max(scored)[2], fid, "label")
    for lemma, pos, fid, pinned in parse_seeds():
        if lemma in STOPLIST or zipf(lemma) < SEED_MIN_ZIPF:
            continue
        sense = resolve_seed(wn, clf, lemma, pos, fid, pinned)
        if sense is not None:
            offer(lemma, pos, sense, fid, "seed")
    return sorted((c for *_, c in best.values()), key=lambda c: (c.lemma, c.pos))


def calibrate(entries: Iterable[Entry], zipf: Zipf) -> list[float]:
    """Zipf thresholds between consecutive CEFR levels (midpoints of level medians)."""
    by_level: dict[str, list[float]] = {l: [] for l in LEVELS}
    for e in entries:
        z = zipf(e.lemma)
        if z > 0:
            by_level[e.level].append(z)
    med = [statistics.median(by_level[l]) if by_level[l] else 0.0 for l in LEVELS]
    return [(med[i] + med[i + 1]) / 2 for i in range(len(LEVELS) - 1)]


def estimate_level(z: float, thresholds: list[float], floor: str = MIN_ESTIMATED_LEVEL) -> str:
    level = LEVELS[-1]
    for i, t in enumerate(thresholds):
        if z >= t:
            level = LEVELS[i]
            break
    return max(level, floor, key=level_index)


# Stems that point a short Wiktionary disambiguator at a field ("programmable electronic
# device" -> it). Worth half a gloss match: enough to break a tie, never to beat overlap.
FIELD_HINTS = {
    "it": {"compu", "progr", "softw", "data", "digit", "elect", "netwo", "inter"},
    "electrical": {"elect", "circu", "curre", "volta", "devic"},
    "physics": {"energ", "physi", "parti", "force", "radia"},
    "math": {"mathe", "numbe", "equat", "geome", "arith", "stati"},
    "chemistry": {"chemi", "eleme", "atom", "molec", "compo", "metal"},
    "engineering": {"machi", "mecha", "engin", "struc", "metal"},
}


def _stems(text: str, skip: Iterable[str] = ()) -> set[str]:
    """Content-word stems (5-letter prefixes: metal ~ metallic, compute ~ computer)."""
    banned = {w.lower()[:5] for w in skip}
    return {t[:5] for t in tokens(text) if len(t) > 2 and t not in STOP_TOKENS} - banned


def pick_tech_sense(senses: list, gloss: str, fid: str, lemma: str = ""):
    """Russian translation sense for a technical meaning: needs gloss overlap or a
    matching field label — otherwise no Russian definition (never guess the sense).
    Overlap is normalised by the sense gloss length: Wiktionary disambiguators are
    short ("metal", "physical quantity"), long glosses match by accident."""
    ref = _stems(gloss, [lemma])
    best, best_key = None, (0.0, 0)
    for s in senses:
        if not s.ru_terms:
            continue
        own = _stems(s.gloss or "", [lemma])
        hits = len(ref & own)
        score = (hits / max(1, len(own))) + (1.0 if label_field(s.gloss) == fid else 0.0) \
            + (0.5 if own & FIELD_HINTS.get(fid, set()) else 0.0)
        key = (score, -len(own))
        if score > 0 and key > best_key:
            best, best_key = s, key
    return best


def build_tech_entries(cands: list[TechCandidate], general: dict[tuple[str, str], Entry], wnsrc, zipf: Zipf,
                       thresholds: list[float]) -> list[Entry]:
    entries: list[Entry] = []
    seen: set[str] = set()
    for c in cands:
        synset = wnsrc.synset(c.synset)
        gloss = clean_gloss(synset.definition())
        if not gloss or leaks(gloss, [c.lemma]):
            continue
        known = general.get((c.lemma.lower(), c.pos))
        level = known.level if known else estimate_level(zipf(c.lemma), thresholds)
        eid = "tech:" + make_id(c.lemma, c.pos)
        if eid in seen:
            continue
        seen.add(eid)
        e = Entry(id=eid, lemma=c.lemma, pos=c.pos, level=level, variants=[c.lemma], deck="tech",
                  domain=c.field, level_source="cefr" if known else "frequency")
        syns = wnsrc.synsets([c.lemma], c.pos)
        e.senses = {s.name() for s in syns}
        e.top_senses = [s.name() for s in syns[:6]]
        wnsrc.apply_synset(e, synset)
        e.definitions.append(Definition(gloss, "en", "wordnet", QUALITY["wordnet"]))
        entries.append(e)
    entries.sort(key=lambda e: (level_index(e.level), e.lemma))
    return entries
