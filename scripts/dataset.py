#!/usr/bin/env python3
"""The mined dataset as pandas frames.

Four views of the same thing:

    conditions  one row per condition, its code, and the list of its symptoms
    symptoms    one row per canonical symptom, with idf
    links       one row per condition-symptom pair, the same data unstacked
    matrix      conditions x symptoms, 0/1 -- what the scorer actually sees

conditions is the one to read; links is the one to group and join on. Neither
is derived from the other at load, they are both built from the same TSVs.

Import it for a session:

    from dataset import frames
    d = frames(); d["links"].head()

Or run it:

    dataset.py                  print a summary of each frame
    dataset.py --v2             read the form contract instead of the string bank
    dataset.py --wide           print the 0/1 matrix's shape and density
    dataset.py --csv out/       write every frame to CSV
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT / "data" / "candidates"


def frames(v2: bool = False) -> dict[str, pd.DataFrame]:
    """The four frames, over the string bank by default or the form contract.

    v2 is what search.py actually retrieves over, so it is the one to read when
    asking why a ranking came out as it did. The bank is kept because the
    evaluation still scores against it. The frames have the same columns either
    way: v2's core_phrase is the bank's canonical under another name, and the
    facet columns on the v2 links are dropped here because nothing downstream
    groups on them.
    """
    conditions = pd.read_csv(CAND / "conditions.tsv", sep="\t", dtype=str)
    if v2:
        symptoms = (pd.read_csv(CAND / "symptoms-v2.tsv", sep="\t")
                    .rename(columns={"core_phrase": "canonical"}))
        links = pd.read_csv(CAND / "condition-symptoms-v2.tsv",
                            sep="\t")[["condition", "symptom_id"]]
    else:
        symptoms = pd.read_csv(CAND / "symptom-bank.tsv", sep="\t")
        links = pd.read_csv(CAND / "condition-symptoms.tsv", sep="\t")

    n = links["condition"].nunique()
    # Same inverse document frequency the scorer uses, surfaced here so the
    # weighting can be read off the frame rather than inferred from the code.
    symptoms["idf"] = np.log((n + 1) / (symptoms["n_conditions"] + 1)) + 1.0

    links = (links
             .merge(symptoms[["symptom_id", "canonical", "idf"]], on="symptom_id")
             .merge(conditions[["slug", "name", "system"]],
                    left_on="condition", right_on="slug", how="left")
             .drop(columns=["slug"])
             .rename(columns={"name": "condition_name"})
             [["condition", "condition_name", "system", "symptom_id", "canonical", "idf"]]
             .sort_values(["condition", "symptom_id"], ignore_index=True))

    # Rarest symptom first: the head of the list is the one that most nearly
    # names the condition, which is what makes the column worth reading.
    grouped = (links.sort_values("idf", ascending=False)
               .groupby("condition")["canonical"].apply(list).rename("symptoms"))
    conditions = conditions.merge(grouped, left_on="slug", right_index=True, how="left")
    conditions["symptoms"] = conditions["symptoms"].apply(
        lambda v: v if isinstance(v, list) else [])
    conditions["n_symptoms"] = conditions["symptoms"].str.len()

    matrix = (pd.crosstab(links["condition"], links["canonical"]) > 0).astype(int)

    return {"conditions": conditions, "symptoms": symptoms,
            "links": links, "matrix": matrix}


def main() -> None:
    d = frames(v2="--v2" in sys.argv)
    pd.set_option("display.width", 130, "display.max_columns", 20)

    if "--csv" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--csv") + 1])
        out.mkdir(parents=True, exist_ok=True)
        for name, df in d.items():
            if name == "conditions":
                # A list in a cell has no CSV representation; join it for the file
                # and keep the list in the frame, where it is useful.
                df = df.assign(symptoms=df["symptoms"].str.join(" | "))
            df.to_csv(out / f"{name}.csv", index=(name == "matrix"))
            print(f"{out / name}.csv  {df.shape}")
        return

    if "--wide" in sys.argv:
        m = d["matrix"]
        print(f"matrix {m.shape[0]} conditions x {m.shape[1]} symptoms, "
              f"density {m.to_numpy().mean():.3%}")
        print(m.iloc[:8, :6])
        return

    show = d["conditions"].copy()
    show["symptoms"] = show["symptoms"].apply(
        lambda v: ", ".join(v)[:70] + ("..." if len(", ".join(v)) > 70 else ""))
    print(f"\n=== conditions  {len(show)} rows x {show.shape[1]} cols ===")
    print(show[["slug", "system", "n_symptoms", "symptoms"]]
          .head(10).to_string(index=False))
    for name in ("symptoms", "links"):
        df = d[name]
        print(f"\n=== {name}  {df.shape[0]} rows x {df.shape[1]} cols ===")
        print(df.head(6).to_string(index=False))

    c = d["conditions"]
    print(f"\nconditions with at least one symptom: {(c.n_symptoms > 0).sum()} "
          f"of {len(c)}")
    print(f"symptoms per condition: median {int(c.loc[c.n_symptoms > 0, 'n_symptoms'].median())}, "
          f"max {c.n_symptoms.max()}")
    print("\nleast informative symptoms (lowest idf):")
    print(d["symptoms"].nsmallest(5, "idf")[["canonical", "n_conditions", "idf"]]
          .to_string(index=False))
    print("\nmost informative symptoms shared by more than one condition:")
    s = d["symptoms"]
    print(s[s.n_conditions > 1].nlargest(5, "idf")[["canonical", "n_conditions", "idf"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
