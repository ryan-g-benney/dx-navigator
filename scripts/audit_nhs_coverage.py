#!/usr/bin/env python3
"""Which of our own variables does an NHS condition page mention that we do not?

Purpose is coverage, not content: the question is whether the knowledge base
forgets to ask something a plain-language description of the condition thinks
worth mentioning. That is the "nothing is missed" check.

Only the derived finding is reported -- our slug, our variable. No NHS wording
is stored in the repository or printed. Pages are cached under .workbench,
which is gitignored, and fetched one per second.

    audit_nhs_coverage.py            report from cache, fetching what is absent
    audit_nhs_coverage.py --refetch  ignore the cache
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".workbench" / "nhs"
# Everything from the first advice callout onwards describes when to seek help,
# and lists the red flags of the serious thing this condition is mistaken for.
# A cue before it belongs to this condition; a cue only after it does not.
ADVICE = re.compile(r"(Urgent advice|Immediate action required|Non-urgent advice)")
UA = "dx-navigator-research/0.1"
sys.path.insert(0, str(ROOT / "packages" / "engine"))
from dx_engine.kb import load  # noqa: E402

# Our variable -> phrases that indicate the page is talking about it. Deliberately
# conservative: a missed cue is a quiet false negative, a loose one is noise.
CUES: dict[str, tuple[str, ...]] = {
    "breathlessness": ("shortness of breath", "breathless", "difficulty breathing",
                       "out of breath", "trouble breathing"),
    "fever_history": ("high temperature", "fever", "feverish", "chills"),
    "cough_character": ("cough",),
    "confusion_new": ("confus", "delirium", "disorient"),
    "chest_pain_present": ("chest pain",),
    "pleuritic_pain": ("worse when you breathe", "pain when breathing",
                       "hurts to breathe"),
    "wheeze_history": ("wheez",),
    "orthopnoea": ("lying down", "lie flat", "propped up"),
    "ankle_oedema": ("swollen ankle", "swelling in your ankle", "swollen legs"),
    "calf_swelling": ("swollen leg", "swelling in one leg", "calf"),
    "neck_stiffness": ("stiff neck", "neck stiffness"),
    "non_blanching_rash": ("rash that does not fade", "glass test",
                           "rash does not fade"),
    "photophobia": ("bright light", "light hurt", "sensitive to light"),
    "visual_disturbance": ("blurred vision", "vision", "seeing halo"),
    "eye_pain_red_eye": ("red eye", "painful eye", "eye pain"),
    "jaw_claudication": ("jaw pain", "chewing"),
    "scalp_tenderness": ("scalp", "tender temple"),
    "weight_loss": ("losing weight", "weight loss"),
    "fatigue": ("tired", "fatigue", "exhaust"),
    "appetite_loss": ("loss of appetite", "not feeling hungry"),
    "autonomic_symptoms": ("sweating", "feeling sick", "clammy", "nausea"),
    "pallor": ("pale", "paler than usual"),
    "recent_immobility": ("long journey", "bed rest", "recently had surgery"),
    "focal_neurology": ("weakness on one side", "slurred speech", "numbness"),
    "coryza": ("blocked nose", "runny nose", "sneezing"),
}

# nhs.uk does not use our slugs. Only the pages that resolve are used; the rest
# are reported as unmatched rather than guessed at.
SLUG = {
    "community-acquired-pneumonia": "pneumonia",
    "acute-bronchitis": "bronchitis",
    "asthma-exacerbation": "asthma",
    "copd-exacerbation": "chronic-obstructive-pulmonary-disease-copd",
    "pulmonary-embolism": "pulmonary-embolism",
    "acute-heart-failure": "heart-failure",
    "atrial-fibrillation": "atrial-fibrillation",
    "lung-cancer": "lung-cancer",
    "pulmonary-tuberculosis": "tuberculosis-tb",
    "bronchiectasis": "bronchiectasis",
    "influenza": "flu",
    "covid-19": "covid-19",
    "pertussis": "whooping-cough",
    "upper-respiratory-tract-infection": "common-cold",
    "iron-deficiency-anaemia": "iron-deficiency-anaemia",
    "gastro-oesophageal-reflux": "heartburn-and-acid-reflux",
    "peptic-ulcer-disease": "stomach-ulcer",
    # No nhs.uk page: pneumothorax, myocarditis and aortic dissection have none
    # under any slug tried, so they are reported as unresolved rather than
    # mapped to a near-miss page that would describe a different condition.
    "pericarditis": "pericarditis",
    "stable-angina": "angina",
    "acute-coronary-syndrome": "heart-attack",
    "costochondritis": "costochondritis",
    "herpes-zoster": "shingles",
    "migraine": "migraine",
    "cluster-headache": "cluster-headaches",
    "tension-type-headache": "headaches",
    "bacterial-meningitis": "meningitis",
    "subarachnoid-haemorrhage": "subarachnoid-haemorrhage",
    "giant-cell-arteritis": "temporal-arteritis",
    "brain-tumour": "brain-tumours",
    "trigeminal-neuralgia": "trigeminal-neuralgia",
    "sinusitis": "sinusitis-sinus-infection",
    "acute-angle-closure-glaucoma": "glaucoma",
    "carbon-monoxide-poisoning": "carbon-monoxide-poisoning",
    "anxiety-related-chest-pain": "generalised-anxiety-disorder",
    # Symptom pages rather than condition pages. For this audit that is if
    # anything better: the page lists the dangerous causes of the presentation,
    # which is exactly the set a benign cause needs to argue against. Several
    # benign headaches share one page for the same reason.
    "medication-overuse-headache": "headaches",
    "cervicogenic-headache": "headaches",
    "oesophageal-spasm": "chest-pain",
    "hyperventilation-syndrome": "chest-pain",
}


# Proposals rejected on clinical grounds, kept so they cannot be re-proposed
# silently. Each is a case where the cue matched but the assertion would be
# wrong, and only reading the entry catches it.
EXCLUDE: dict[tuple[str, str], str] = {
    ("migraine", "visual_disturbance"):
        "visual disturbance is migraine aura; the entry already asserts aura",
    ("cervicogenic-headache", "neck_stiffness"):
        "arises from the cervical spine and asserts neck_movement_provokes; "
        "neck findings are expected, not absent",
}


def page_text(slug: str, refetch: bool) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{slug}.txt"
    if path.exists() and not refetch:
        return path.read_text()
    r = subprocess.run(
        ["curl", "-sSL", "-m", "40", "-A", UA, "-w", "\\n%{http_code}",
         f"https://www.nhs.uk/conditions/{slug}/"],
        capture_output=True, text=True, check=False)
    raw, _, code = r.stdout.rpartition("\n")
    time.sleep(1)  # one page per second
    if code.strip() != "200":
        return None
    m = re.search(r"(?is)<main.*?</main>", raw)
    body = re.sub(r"(?is)<(script|style|nav|footer|svg)[^>]*>.*?</\1>", " ",
                  m.group(0) if m else raw)
    body = re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", body)))
    path.write_text(body.strip())
    return body.strip()


def main() -> None:
    refetch = "--refetch" in sys.argv
    kb = load(ROOT / "data")
    missing_total = 0
    unmatched = []

    for slug, nhs in sorted(SLUG.items()):
        if slug not in kb.conditions:
            continue
        text = page_text(nhs, refetch)
        if text is None:
            unmatched.append(f"{slug} ({nhs})")
            continue
        split = ADVICE.search(text)
        own = text[:split.start()].lower() if split else text.lower()
        advice = text[split.start():].lower() if split else ""
        cond = kb.conditions[slug]

        here_own, here_flag = [], []
        for var, cues in CUES.items():
            if var in cond.features or var not in kb.variables:
                continue
            if any(c in own for c in cues):
                here_own.append(var)
            elif any(c in advice for c in cues):
                here_flag.append(var)
        if here_own or here_flag:
            missing_total += len(here_own) + len(here_flag)
            print(f"  {slug}")
            if here_own:
                print(f"      describes:  {', '.join(sorted(here_own))}")
            if here_flag:
                print(f"      red flag:   {', '.join(sorted(here_flag))}")

    print(f"\n{missing_total} variable mentions our entries do not assert")
    covered = len([s for s in SLUG if s in kb.conditions]) - len(unmatched)
    print(f"{covered} conditions checked, {len(kb.conditions) - covered} not mapped")
    if unmatched:
        print(f"page did not resolve: {', '.join(unmatched)}")


if __name__ == "__main__":
    main()
