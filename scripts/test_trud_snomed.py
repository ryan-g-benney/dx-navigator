#!/usr/bin/env python3
"""Exercise the RF2 parsing and graph walks against a synthetic release.

The real archive is ~1 GB and needs a TRUD subscription, so the graph logic is
checked here on a hand-built zip with the same column layout.
"""
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import trud_snomed as t  # noqa: E402

COLS = ("id\teffectiveTime\tactive\tmoduleId\tsourceId\tdestinationId\t"
        "relationshipGroup\ttypeId\tcharacteristicTypeId\tmodifierId")


def row(src, dst, type_id=t.IS_A, active="1"):
    return f"1\t20240101\t{active}\t900\t{src}\t{dst}\t0\t{type_id}\t900\t900"


def archive(rows, tmp: Path) -> Path:
    z = tmp / "uk_sct2cl_synthetic.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("SnomedCT_UKClinicalRF2/Snapshot/Terminology/sct2_Relationship_UKCLSnapshot_GB1000000_20240101.txt",
                   "\n".join([COLS, *rows]) + "\n")
    return z


with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)

    # b -> a, c -> b, plus an inactive edge and a non-is-a edge that must be dropped.
    z = archive([row("b", "a"), row("c", "b"),
                 row("x", "y", active="0"),
                 row("p", "q", type_id="42")], tmp)
    # Full and Delta must not be counted, and Stated is not the inferred view.
    with zipfile.ZipFile(z, "a") as f:
        for path in ("SnomedCT_UKClinicalRF2/Full/Terminology/sct2_Relationship_UKCLFull_GB1000000_20240101.txt",
                     "SnomedCT_UKClinicalRF2/Snapshot/Terminology/sct2_StatedRelationship_UKCLSnapshot_GB1000000_20240101.txt",
                     "SnomedCT_UKClinicalRF2/Snapshot/Terminology/sct2_RelationshipConcreteValues_UKCLSnapshot_GB1000000_20240101.txt"):
            f.writestr(path, "\n".join([COLS, row("must", "not_appear")]) + "\n")
    parents = t.is_a_edges(z)
    assert parents == {"b": {"a"}, "c": {"b"}}, parents
    assert t.ancestors(parents, "c") == {"a", "b"}
    assert t.ancestors(parents, "a") == set()
    t.assert_acyclic(parents)  # must not exit

    # Multi-parent: the PE case the DAG requirement exists for.
    z = archive([row("pe", "resp"), row("pe", "vasc"), row("resp", "clin"),
                 row("vasc", "clin")], tmp)
    assert t.ancestors(t.is_a_edges(z), "pe") == {"resp", "vasc", "clin"}

    # A cycle must be caught, not walked forever.
    z = archive([row("a", "b"), row("b", "a")], tmp)
    try:
        t.assert_acyclic(t.is_a_edges(z))
    except SystemExit as e:
        assert "cycle" in str(e), e
    else:
        raise AssertionError("cycle not detected")

print("trud_snomed graph logic ok")
