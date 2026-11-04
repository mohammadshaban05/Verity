# ruff: noqa: E501  (evidence quotes are verbatim and are not wrapped)
"""Write the gold set (data/eval/claims.jsonl) for the seed corpus.

Usage:
    uv run python scripts/build_gold.py [--scifact DIR] [--out FILE]

Records exactly how each gold claim was made (ADR-012, ADR-013):

* SciFact: the same seeded, label-stratified sample of dev claims that
  ``select_corpus.py`` uses. One evidence quote per annotated rationale sentence;
  the stance follows SciFact's label. NEI claims get no evidence.
* FEVER: dev-set claims about the pinned FEVER articles, re-verified by hand
  against the pinned revision. The quotes and labels are ours; where the label
  differs from FEVER's, the note says so and why.
* WikiContradict: one claim per article, with one quote for each side of the
  reported contradiction, copied verbatim from the pinned revision.
* Verity: claims written for this project to test agreement and conflict
  between two separately written sources.
* Pooling: direct evidence found later among top-ranked passages that were not
  yet in the gold set, marked "Gold extended by pooling." in the note.

The label is never written by hand: it follows from the evidence stances, as
``GoldClaim`` requires.
"""

import argparse
import importlib.util
import json
import random
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "select_corpus", Path(__file__).with_name("select_corpus.py")
)
assert _spec and _spec.loader
sel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sel)


def ev(doc, quote, stance="supports"):
    return {"doc_id": doc, "quote": quote, "stance": stance}


def claim(cid, text, topic, origin, evidence, note=""):
    stances = {e["stance"] for e in evidence}
    label = (
        "insufficient"
        if not stances
        else "supported"
        if stances == {"supports"}
        else "contradicted"
        if stances == {"contradicts"}
        else "conflicting"
    )
    return {
        "id": cid,
        "claim": text,
        "label": label,
        "topic": topic,
        "origin": origin,
        "evidence": evidence,
        "note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scifact", type=Path, help="directory with an extracted SciFact data/")
    parser.add_argument("--out", type=Path, default=Path("data/eval/claims.jsonl"))
    args = parser.parse_args()
    scifact_dir, out_path = args.scifact, args.out

    # --- SciFact: same seeded sample as scripts/select_corpus.py -------------------------
    claims_dev, corpus = sel.load_scifact(scifact_dir)
    rng = random.Random(sel.SEED)
    by_label = {label: [] for label in sel.SCIFACT_SAMPLE}
    for c in claims_dev:
        labels = {a["label"] for anns in c["evidence"].values() for a in anns}
        by_label["NEI" if not labels else labels.pop()].append(c)
    out = []
    n = 0
    for label, k in sel.SCIFACT_SAMPLE.items():
        for c in rng.sample(by_label[label], k):
            n += 1
            evidence = []
            for doc_id, anns in c["evidence"].items():
                sentences = corpus[int(doc_id)]["abstract"]
                for a in anns:
                    for i in a["sentences"]:  # one quote per rationale sentence
                        evidence.append(
                            ev(
                                f"scifact-{doc_id}",
                                " ".join(sentences[i].split()),
                                "supports" if a["label"] == "SUPPORT" else "contradicts",
                            )
                        )
            note = f"SciFact label {label}."
            if label == "NEI":
                note += " Cited abstract(s) are in the corpus but do not address the claim."
            out.append(
                claim(
                    f"sci-{n:02d}",
                    c["claim"],
                    "biomedicine",
                    f"scifact:dev:{c['id']}",
                    evidence,
                    note,
                )
            )

    # --- FEVER claims, re-verified against the pinned revisions -------------------------
    E, S = "wiki-", "simplewiki-"
    fever = [
        (
            "94382",
            "Elizabeth of York's father was Edward IV.",
            "history",
            [
                ev(
                    E + "elizabeth-of-york",
                    "She was the daughter of King Edward IV and Elizabeth Woodville",
                ),
                ev(
                    S + "elizabeth-of-york",
                    "She was the daughter of Edward IV of England and of Elizabeth Woodville.",
                ),
            ],
            "",
        ),
        (
            "137094",
            "Elizabeth of York's uncle was Richard III.",
            "history",
            [
                ev(
                    E + "elizabeth-of-york",
                    "It was rumoured that Richard was plotting to marry his niece Elizabeth.",
                ),
                ev(E + "elizabeth-of-york", "Niece of King Richard III"),
            ],
            "",
        ),
        (
            "87570",
            "Elizabeth of York was the mother of Richard III.",
            "history",
            [
                ev(E + "elizabeth-of-york", "Niece of King Richard III", "contradicts"),
                ev(
                    E + "elizabeth-of-york",
                    "It was rumoured that Richard was plotting to marry his niece Elizabeth.",
                    "contradicts",
                ),
            ],
            "",
        ),
        (
            "12897",
            "Elizabeth of York had several children including Mary and Arthur.",
            "history",
            [
                ev(
                    E + "elizabeth-of-york",
                    "She gave birth to several more children, but only four survived infancy: Arthur, Margaret, Henry and Mary.",
                )
            ],
            "FEVER label NOT ENOUGH INFO (FEVER used lead sections only); the full article supports it.",
        ),
        (
            "75075",
            "Elizabeth of York had several heart attacks.",
            "history",
            [],
            "FEVER label NOT ENOUGH INFO. Lexical trap: the article says her death 'broke the heart' of her husband.",
        ),
        (
            "204347",
            "The Cretaceous finished with a large mass extinction.",
            "geology",
            [
                ev(
                    E + "cretaceous",
                    "The Cretaceous (along with the Mesozoic) ended with the Cretaceous–Paleogene extinction event, a large mass extinction",
                )
            ],
            "",
        ),
        (
            "204355",
            "In the Cretaceous pterosaurs and large marine reptiles prospered and continued their survival.",
            "geology",
            [
                ev(
                    E + "cretaceous",
                    "a large mass extinction in which many groups, including non-avian dinosaurs, pterosaurs, and large marine reptiles, died out",
                    "contradicts",
                ),
                ev(
                    E + "cretaceous",
                    "as the Cretaceous proceeded they declined for poorly understood reasons",
                    "contradicts",
                ),
            ],
            "",
        ),
        (
            "130637",
            "The head of the dodo has been depicted as grey.",
            "biology",
            [
                ev(
                    E + "dodo",
                    "It has been depicted with brownish-grey plumage, yellow feet, a tuft of tail feathers, a grey, naked head, and a black, yellow, and green beak.",
                ),
                ev(E + "dodo", "The head was grey and naked"),
            ],
            "",
        ),
        (
            "41840",
            "The Dodo has been depicted with orange plumage.",
            "biology",
            [
                ev(
                    E + "dodo",
                    "It has been depicted with brownish-grey plumage, yellow feet, a tuft of tail feathers, a grey, naked head, and a black, yellow, and green beak.",
                    "contradicts",
                ),
                ev(S + "dodo", "They had grey feathers and yellow feet.", "contradicts"),
            ],
            "",
        ),
        (
            "165226",
            "Phillip Glass has written eleven concertos.",
            "music",
            [
                ev(
                    E + "philip-glass",
                    "15 symphonies, 12 concertos, nine string quartets",
                    "contradicts",
                )
            ],
            "FEVER label SUPPORTS (2017 text). The pinned 2026 revision says 12 concertos; read as an exact count, it contradicts. Claim misspells 'Philip'.",
        ),
        (
            "165245",
            "There are no musical or creative works in existence that have been created by Phillip Glass.",
            "music",
            [
                ev(
                    E + "philip-glass",
                    "He has written 15 operas, numerous chamber operas and musical theatre works, 15 symphonies, 12 concertos, nine string quartets",
                    "contradicts",
                )
            ],
            "Claim misspells 'Philip'.",
        ),
        (
            "173499",
            "Sancho Panza is a character in a poem written by Don Miguel de Cervantes Saavedra.",
            "literature",
            [
                ev(
                    E + "sancho-panza",
                    "is a fictional character in the novel Don Quixote written by Spanish author Miguel de Cervantes Saavedra in 1605",
                    "contradicts",
                )
            ],
            "Lexical trap: the article also mentions Richard Strauss's tone poem Don Quixote.",
        ),
        (
            "189437",
            "Yandex functions in Turkey.",
            "technology",
            [
                ev(
                    E + "yandex",
                    "the company launched its web portal in Turkey in 2011 and opened an office in Istanbul",
                )
            ],
            "",
        ),
        (
            "189447",
            "Yandex is a newspaper.",
            "technology",
            [
                ev(
                    E + "yandex",
                    "is a Russian technology company that provides Internet-related products and services",
                    "contradicts",
                ),
                ev(S + "yandex", "is a Russian internet company and search engine", "contradicts"),
            ],
            "",
        ),
        (
            "189454",
            "Yandex operates in Belgium.",
            "technology",
            [],
            "FEVER label REFUTES (inferred from a list of countries). Neither text mentions Belgium, so the corpus does not address it.",
        ),
        (
            "138814",
            "The highest point of the Hindu Kush is Tirich Mir in Khyber Pakhtunkhwa.",
            "geography",
            [
                ev(
                    E + "hindu-kush",
                    "with the highest point being Tirich Mir or Terichmir at 7,708 metres (25,289 ft) in the Chitral District of Khyber Pakhtunkhwa, Pakistan",
                )
            ],
            "",
        ),
        (
            "60977",
            "The highest point of the Hindu Kush is Everest.",
            "geography",
            [
                ev(
                    E + "hindu-kush",
                    "with the highest point being Tirich Mir or Terichmir at 7,708 metres (25,289 ft) in the Chitral District of Khyber Pakhtunkhwa, Pakistan",
                    "contradicts",
                )
            ],
            "",
        ),
        (
            "105796",
            "Part of Hindu Kush is higher than the Himalayas.",
            "geography",
            [],
            "FEVER label NOT ENOUGH INFO. The article places the range west of the Himalayas but does not compare heights.",
        ),
        (
            "32820",
            "The heart beats at a resting rate close to 22 beats per minute.",
            "anatomy",
            [
                ev(
                    E + "heart",
                    "The adult heart beats at a resting rate close to 72 beats per minute.",
                    "contradicts",
                ),
                ev(
                    E + "heart",
                    "The adult resting heart rate ranges from 60 to 100 bpm.",
                    "contradicts",
                ),
            ],
            "",
        ),
        (
            "75032",
            "Aerobic exercise lowers resting heart rate in the long term.",
            "anatomy",
            [],
            "FEVER label SUPPORTS (2017 text). The pinned revision no longer states this; 'An athlete's heart rate can be lower than 60 bpm' is related but does not state the effect of exercise.",
        ),
        (
            "73879",
            "A near-Earth object is a small Solar System body.",
            "astronomy",
            [
                ev(
                    E + "near-earth-object",
                    "A near-Earth object (NEO) is by definition any small Solar System body orbiting the Sun",
                )
            ],
            "",
        ),
        (
            "7782",
            "A near-Earth object is one whose orbit brings it into proximity with Earth.",
            "astronomy",
            [
                ev(
                    S + "near-earth-object",
                    "A near-Earth object (NEO) is a Solar System object whose orbit brings it close to the Earth.",
                )
            ],
            "The English article now defines NEOs by perihelion distance instead; only the Simple English article states this directly.",
        ),
        (
            "123108",
            "A near-Earth object is abbreviated as NGO.",
            "astronomy",
            [
                ev(
                    E + "near-earth-object",
                    "A near-Earth object (NEO) is by definition",
                    "contradicts",
                ),
                ev(
                    S + "near-earth-object",
                    "A near-Earth object (NEO) is a Solar System object",
                    "contradicts",
                ),
            ],
            "",
        ),
    ]
    for i, (fid, text, topic, evidence, note) in enumerate(fever, start=1):
        out.append(
            claim(f"fever-{i:02d}", text, topic, f"fever:shared_task_dev:{fid}", evidence, note)
        )

    # --- WikiContradict: contradictions inside one article --------------------------------
    wc = [
        (
            "46",
            "Two people still speak the Munsee language.",
            "linguistics",
            "munsee-language",
            "As of 2018, Munsee was spoken only on the Moraviantown Reserve in Ontario, Canada, by two elderly individuals, aged 77 and 90",
            "Currently, the Munsee language has eight native speakers",
        ),
        (
            "25",
            "The US Navy began using Whitehead torpedoes in 1894.",
            "technology",
            "torpedo",
            "The Howell torpedo was the only United States Navy model until Whitehead torpedoes produced by Bliss and Williams entered service in 1894.",
            "The United States Navy started using the Whitehead torpedo in 1892",
        ),
        (
            "77",
            "Human plasma cells express CD19.",
            "biomedicine",
            "cd19",
            "Contrary to some early doubts, human plasma cells do express CD19, as confirmed by others.",
            "CD19 is expressed on all normal, mitogen-stimulated, and malignant B cells, excluding plasma cells.",
        ),
        (
            "100",
            "The Asian tiger mosquito can lay its eggs in moving water.",
            "biology",
            "aedes-albopictus",
            "It can also breed in running water, so stagnant pools of water are not its only breeding sites.",
            "Flowing water will not be a breeding spot",
        ),
        (
            "78",
            "Only two monks know the secret recipe for Chartreuse.",
            "food",
            "chartreuse-liqueur",
            "Today, the liqueurs are produced using the herbal mixture prepared by two monks at Grande Chartreuse. They are the only ones to know the secret recipe.",
            "known at any given time only to the three monks who prepare the herbal mixture",
        ),
        (
            "98",
            "Azelaic acid works as well as benzoyl peroxide for treating acne.",
            "biomedicine",
            "acne",
            "Treatment twice daily for six months is necessary, and is as effective as topical benzoyl peroxide 5%",
            "Azelaic acid also led to worse treatment response when compared to benzoyl peroxide.",
        ),
        (
            "174",
            "By area, Bremen is the fifth largest city in Germany.",
            "geography",
            "bremen",
            "5th largest city by area with area of 318.21 km2",
            "In terms of area, Bremen is the eleventh largest city in Germany",
        ),
        (
            "14",
            "The spiral staircase of the Loretto Chapel was built without glue.",
            "architecture",
            "loretto-chapel",
            "is held together by wooden pegs, with no glue, nails or other hardware used",
            "the assembly of the stringers from overlapping segments joined by wood glue",
        ),
    ]
    for i, (qid, text, topic, slug, pro, con) in enumerate(wc, start=1):
        out.append(
            claim(
                f"wc-{i:02d}",
                text,
                topic,
                f"wikicontradict:{qid}",
                [ev(E + slug, pro), ev(E + slug, con, "contradicts")],
                "Both passages are in the same article (an internal contradiction).",
            )
        )

    # --- Cross-source claims written for Verity ----------------------------------------------
    own = [
        (
            "Yandex launched its search engine in 1997.",
            "technology",
            [
                ev(
                    E + "yandex",
                    "Yandex was founded by Arkady Volozh and launched its first product, a search engine, in 1997.",
                ),
                ev(E + "yandex", "On 23 September 1997, the Yandex.ru search engine was launched"),
                ev(
                    S + "yandex",
                    "The company was originally founded in 2000 by Arkady Volozh but the website didn't start until 2006.",
                    "contradicts",
                ),
            ],
            "Cross-source conflict: English vs Simple English Wikipedia.",
        ),
        (
            "The Cretaceous period ended 66 million years ago.",
            "geology",
            [
                ev(
                    E + "cretaceous",
                    "is a geological period that lasted from about 143.1 to 66 Ma (million years ago)",
                ),
                ev(
                    S + "cretaceous",
                    "lasting 80 million years from 145 to 65 million years ago (mya)",
                    "contradicts",
                ),
            ],
            "Cross-source conflict on a number (66 vs 65 million years). The label records that the texts disagree, not which dating is current.",
        ),
        (
            "Animals that people brought to Mauritius did more harm to the dodo than hunting.",
            "biology",
            [
                ev(
                    E + "dodo",
                    "The impact of the introduced animals on the dodo population, especially the pigs and macaques, is today considered more severe than that of hunting.",
                ),
                ev(
                    S + "dodo",
                    "They became extinct in the late 17th century due to the predators introduced by the Europeans.",
                ),
            ],
            "Two sources agree; the Simple English quote supports the claim less directly (it names introduced predators as the cause).",
        ),
    ]
    for i, (text, topic, evidence, note) in enumerate(own, start=1):
        out.append(claim(f"verity-{i:02d}", text, topic, "verity", evidence, note))

    # --- Pooling (ADR-012): direct evidence found among top-ranked non-gold passages -------
    POOLED = {
        "sci-10": [
            ev(
                "scifact-21366394",
                "We found that CX3CR1 signaling promoted T(H)2 survival in the inflamed lungs, and injection of B cell leukemia/lymphoma-2 protein (BCl-2)-transduced CX3CR1-deficient T(H)2 cells into CX3CR1-deficient mice restored asthma.",
                "contradicts",
            )
        ],
        "fever-01": [
            ev(
                E + "elizabeth-of-york",
                "as the eldest child of King Edward IV and his wife, Elizabeth Woodville",
            )
        ],
        "fever-11": [
            ev(
                E + "philip-glass",
                "Glass's new works met with a very enthusiastic response by the audience",
                "contradicts",
            ),
            ev(
                E + "philip-glass",
                'In the mid-1980s, Glass produced "works in different media at an extraordinarily rapid pace".',
                "contradicts",
            ),
        ],
        "fever-21": [
            ev(
                E + "near-earth-object",
                "Near-Earth objects (NEOs) are formally defined by the International Astronomical Union (IAU) as all small Solar System bodies",
            ),
            ev(
                E + "near-earth-object",
                "When an NEO is detected, like all other small Solar System bodies",
            ),
        ],
        "fever-23": [
            ev(
                E + "near-earth-object",
                "Near-Earth objects (NEOs) are formally defined",
                "contradicts",
            )
        ],
    }
    for c in out:
        if c["id"] in POOLED:
            c["evidence"] += POOLED.pop(c["id"])
            c["note"] = (c["note"] + " " if c["note"] else "") + "Gold extended by pooling."
    assert not POOLED, POOLED

    out_path.write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out), encoding="utf-8"
    )
    print(f"wrote {len(out)} claims to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
