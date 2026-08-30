# Extraction contract — NICE rules

Target format for `data/complaints/<complaint>/rules.yaml`. Read
`packages/engine/dx_engine/kb.py` for the authoritative schema.

## Licensing — non-negotiable

NICE guidance is reusable under the NICE UK Open Content Licence, which
**prohibits amending or adapting the wording of published recommendations**.
So:

- `text_verbatim` is a **character-for-character copy** of the recommendation.
  Never paraphrase, never summarise, never tidy the grammar. You may trim
  leading/trailing whitespace and collapse internal runs of whitespace to a
  single space. Nothing else.
- Every source needs the NICE attribution string in this exact shape:
  `© NICE <YEAR> <TITLE>. Available from <URL> All rights reserved. Subject to Notice of rights.`
- **Never fetch or quote anything from `cks.nice.org.uk`.** It is third-party
  content under a separate EULA and the loader rejects it. NG/CG/QS only.
- Use current NICE terminology. NG12 says "suspected cancer pathway referral",
  not "2-week-wait".

## Shape

```yaml
sources:
  ng12:
    type: guideline
    title: "Suspected cancer: recognition and referral"
    url: https://www.nice.org.uk/guidance/ng12
    licence: https://www.nice.org.uk/reusing-our-content/nice-uk-open-content-licence
    attribution: "© NICE 2015 Suspected cancer: recognition and referral. Available from www.nice.org.uk/guidance/ng12 All rights reserved. Subject to Notice of rights."

variables:
  haemoptysis:
    prompt: "Has the patient coughed up blood?"
    modality: history          # history | examination | point_of_care ONLY
    role: discriminating       # or disposition
    cost: 0                    # 0 history, 1-3 examination, higher point_of_care
    values: [present, absent, unknown]

rules:
  ng12-lung-1.1.1:
    complaints: [acute-cough]
    all_of:
      - {var: age_years, op: ">=", value: 40}
      - {var: haemoptysis, op: "==", value: present}
    emit:
      kind: referral           # referral | escalation | investigation | safety_net | must_ask
      urgency: urgent          # routine | urgent | same_day | emergency
      text_verbatim: "Refer people using a suspected cancer pathway referral for lung cancer if they: have chest X-ray findings that suggest lung cancer, or are aged 40 and over with unexplained haemoptysis."
      source: ng12
```

## Rules about rules

- **Rules never chain.** Each is a standalone predicate over the answer set.
  No rule may reference another rule or a fact a rule derived.
- **Rules emit actions, never evidence.** There is no field that touches a
  probability or a ranking. If you find yourself wanting one, the thing is a
  feature on a condition, not a rule.
- A rule with no `all_of` and no `any_of` is rejected — it would always fire.
- Every variable you reference in a clause must be declared in `variables:`.
- Prompts: must end in `?`, 15 words max, no "and"/"or"/"perhaps"/"at all",
  one concept each, values mutually exclusive and always including `unknown`.

## Fetching

`curl -sSL -A "dx-navigator-research/0.1" "<nice url>"` works; nice.org.uk
robots allows it with `Crawl-delay: 1`, so sleep 1s between fetches. Strip tags
and extract the numbered recommendations. Prefer the
`/chapter/recommendations...` pages.

## What to skip

- Recommendations that are not actionable from a GP consultation (in-hospital
  management, surgical technique, commissioning).
- Anything requiring an investigation result you would not have in the room —
  those become `kind: investigation` emits (an output), never a question.
