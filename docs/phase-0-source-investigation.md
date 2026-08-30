# Phase 0 addendum — Source and licensing investigation

**Date:** 2026-08-30
**Status:** findings. Three items amend the Phase 0 architecture position.
**Method:** direct fetch of primary sources (terms pages, robots.txt, guideline
text, NCBI E-utilities). Everything below was retrieved, not recalled.

---

## 1. Direct answer: can we scrape Mayo Clinic or NHS.uk?

**No, and we should not want to.**

**Mayo Clinic** — `https://www.mayoclinic.org/robots.txt` does not return a
robots file. It returns an Akamai `Access Denied` page. The site is edge-blocked
against non-browser clients, so there is no permission to read, let alone reuse.
Separately it is the wrong source on the merits: US patient-facing content,
fully copyrighted, and it contains no UK primary-care base rates — which §4 of
the brief correctly identifies as the number that matters most.

**NHS.uk** — `https://www.nhs.uk/robots.txt` contains, under `User-agent: *`:

```
Disallow: /Conditions/
```

The condition pages are exactly what we would have wanted, and they are exactly
what the NHS disallows crawling. This is not an oversight; they publish a free
syndication API instead, and expect you to use it. So: **API, never scrape.**

**NICE** — `https://www.nice.org.uk/robots.txt` is permissive (`Allow: /`,
`Crawl-delay: 1`) and notably disallows only two paths, both CKS licensing pages.
But robots.txt governs crawling, not reuse. Reuse is governed by the licence, and
that is where the real constraints are — see §2.

---

## 2. Licensing — three findings that change the brief

### 2.1 The NICE UK Open Content Licence is usable, with one sharp edge

Verified from `https://www.nice.org.uk/reusing-our-content/nice-uk-open-content-licence`.

Permitted: *"exploit the information commercially and non-commercially — for
example, by combining it with other information, or by including it in your own
product or application."* That covers what we want to do.

Required, and directly relevant to us — attribution applies *"including if the
content is not visible but used to underpin a product in part or in full"*.
A knowledge base compiled from NICE guidance is precisely "not visible but used
to underpin". The prescribed form of words is:

> `© NICE [YEAR] TITLE. Available from www.nice.org.uk/guidance/ngXX All rights
> reserved. Subject to Notice of rights ...`

Prohibited: *"amend or adapt the wording or structure of any published individual
NICE guidance recommendations, quality statements or substantial algorithms.
These should be reproduced as originally published by NICE."*

**This last clause is a design constraint, and it happens to be a good one.**
Paraphrasing a NICE referral criterion into a rule's message string is
non-compliant. The compliant pattern is to store the recommendation **verbatim**
as a quoted string with its attribution block, and have the rule *trigger the
display of* that verbatim text rather than restate it. That is also the more
auditable design: a GP checking our working sees NICE's words, not ours. The
licence and the safety requirement point the same way, which is unusual and worth
taking.

### 2.2 "AI purposes" are carved out of the licence entirely

NICE terms and conditions, clause 18.3, verbatim:

> "Copyright content owned by the National Institute for Health and Care
> Excellence (NICE) may be made available to individuals and
> commercial/non-commercial organisations on a non-exclusive basis for artificial
> intelligence (AI) purposes. All requests, without exception, are subject to an
> approval process, licensing arrangement and a fee (for international use)."

And on the open content licence page: *"Requests to use our content for
artificial intelligence (AI) purposes in the United Kingdom and internationally
are not covered by the terms of this licence."*

Whether dx-navigator is an "AI purpose" is genuinely arguable — the engine is
naive Bayes over a hand-authored table, not a model trained on NICE text. But the
knowledge base is being *authored* with LLM assistance from NICE source material,
and NICE has not defined the boundary publicly. **This needs the same legal
conversation as the UK MDR question in §9 of the brief, and it should go in the
same email.** I am flagging, not ruling.

### 2.3 CKS is not NICE content, and this is the finding that most changes the plan

NICE terms and conditions, clause 18.8, verbatim:

> "In respect of the content on the NICE Clinical Knowledge Summaries site
> (content on all pages within the domain https://cks.nice.org.uk). This content
> is the copyright of Clarity Informatics Limited (trading as Agilio Software
> Primary Care) ... By accessing the NICE Clinical Knowledge Summaries site, all
> users agree to the licence set out in the CKS End User Licence Agreement
> (EULA)."

And clause 18.3: *"the British National Formulary (BNF) and the British National
Formulary for Children (BNFc) and NICE Clinical Knowledge Summaries is
third-party content hosted on the NICE website on behalf of the respective
publishers. It is not NICE content and cannot be used for artificial intelligence
(AI) purposes without the express permission of the respective publishers."*

The open content licence page states it plainly: *"Clinical Knowledge Summaries
and the British National Formulary are not covered by the terms of this
licence."* Access is via a EULA scoped to NHS employees acting for NHS benefit,
and to students for their own education. Commercial or institutional use requires
a separate licence.

**Consequence for the brief.** §4 instructs "verify against the actual NICE CKS
pages" and §9 requires "Every recommendation carries its NICE guideline link".
That plan does not survive contact with the licence. Revised position:

- **Primary reusable source becomes NICE guidelines** (NG / CG / QS) under the
  open content licence, not CKS.
- **CKS may be read** by an NHS-affiliated clinician reviewing our work, and **may
  be deep-linked** — a URL is not content.
- **No CKS text, table, or number is copied into `data/`.** The knowledge-base
  validator should carry a lint that fails the build on any `provenance.url`
  under the `cks.nice.org.uk` domain, so this cannot be violated by accident six
  months from now. That is a two-line check and it is worth having.

---

## 3. The brief's worked example is wrong, and the real rule is simpler

The brief uses "haemoptysis + age ≥ 40 + smoker ⇒ 2-week-wait referral" as the
canonical example of categorical clinical policy. Fetched from NG12
(`https://www.nice.org.uk/guidance/ng12/chapter/recommendations-organised-by-site-of-cancer`),
recommendation 1.1.1 verbatim:

> "Refer people using a suspected cancer pathway referral for lung cancer if they:
> have chest X‑ray findings that suggest lung cancer, or are aged 40 and over with
> unexplained haemoptysis. [2015]"

Smoking is **not** a criterion. It appears in 1.1.2, which governs a different
action (an urgent direct-access chest X-ray, not a referral) and a different
symptom set:

> "Offer an urgent, direct access chest X‑ray to assess for lung cancer in people
> aged 40 and over if they have 2 or more of the following unexplained symptoms,
> or if they have ever smoked and have 1 or more of the following unexplained
> symptoms: cough, fatigue, shortness of breath, chest pain, weight loss,
> appetite loss. [2015]"

Two things follow. First, the architectural argument in the Phase 0 position
survives unchanged and is in fact strengthened — the real rule is *simpler* than
the brief assumed and even less like a likelihood. Second, note that NG12 no
longer uses "2-week-wait"; the current term is **"suspected cancer pathway
referral"**. We should use NICE's current terminology, or a GP will notice
immediately and mark us as out of date.

This is the cheapest possible demonstration of why source-driven authoring is not
ceremony: one fetch corrected the flagship example in the brief.

---

## 4. Where the numbers actually come from

This is the hard half. NICE guidelines give us **rules**; they do not give us
**base rates in UK primary care**. Four candidate sources, assessed.

### 4.1 PubMed Central via NCBI E-utilities — recommended, and verified working

Tested live, no API key required:

```
esearch.fcgi?db=pmc&term=<query>        → PMC ids
efetch.fcgi?db=pmc&id=<id>&retmode=xml  → full-text JATS XML
```

The returned XML carries a machine-readable licence node. From the test fetch of
PMC4897548:

```xml
<permissions>
  <copyright-statement>Copyright © 2014 Thomas Frese et al.</copyright-statement>
  <license xlink:href="https://creativecommons.org/licenses/by/3.0/">
    <ali:license_ref specific-use="textmining"
      content-type="ccbylicense">https://creativecommons.org/licenses/by/3.0/</ali:license_ref>
```

Note `specific-use="textmining"`. The licence is explicit, per-article, and
machine-readable.

**This is a design win worth taking into the schema.** The knowledge-base loader
can require a licence URI on every literature-sourced assertion and verify it
against the article record, rather than trusting an author to fill in a
provenance field honestly. §4 of the brief asks for provenance on every clinical
assertion; this makes it enforceable rather than aspirational. Add
`provenance.licence` alongside `provenance.url` and `provenance.type`.

### 4.2 Dutch Transition Project — the best-shaped data that exists

Okkes, Oskam and Lamberts, AMC Amsterdam. 504,145 episodes of care over 168,550
patient-years, 1985–2000, 58 family physicians, coded in ICPC. It publishes
**prior and posterior probabilities of diagnosis given reason for encounter** —
which is, structurally, precisely the table dx-navigator's engine consumes.

Three caveats, all material:

1. **Dutch, not UK.** Dutch and UK general practice are similar in gatekeeping
   structure, which makes it far better than any hospital or US source, but it is
   not the UK and the knowledge base must say so in the provenance field.
2. **Dated** (1985–2000). Base rates move.
3. **Availability risk:** `https://transitieproject.nl/` currently returns
   **HTTP 503**. The canonical distribution was a CD-ROM. If we want this data we
   should establish now whether we can get it, because a large part of the
   authoring plan leans on it.

### 4.3 RCGP Research and Surveillance Centre — UK, and right for complaint 1

Sentinel network running since 1957, publishing weekly incidence per 100,000
presenting to primary care in England and Wales, broken down by region and age
band, for respiratory and infectious conditions. That is a direct fit for the
acute cough / breathlessness complaint we build first, and it is UK data.

It is not a general symptom-to-diagnosis source, so it will not carry chest pain
or headache.

### 4.4 CPRD — the UK gold standard, and out of scope here

Protocol approval and fees. Not achievable inside this project. The practical
route is CPRD-derived studies already published in the open literature, reached
through §4.1 — for example, an incidence of a new diagnosis of unspecified chest
pain of 15.5 per 1000 person-years from the UK General Practice Research
Database.

### 4.5 Consequence for the authoring format

The 7-point ordinal proposed in §5.2 of the Phase 0 position stands, and this
investigation strengthens the case for it. The literature simply does not exist
at the density we need — there is no source that gives a UK primary-care
likelihood ratio for every cell of our table. Most cells will be `estimate` with
a clinician's ordinal judgement; a minority will be `published` with a PMC
citation and a verified licence. The schema must make that distinction visible in
the UI, exactly as §4 of the brief requires, because **most of the knowledge base
will be expert estimate and the tool must not pretend otherwise.**

---

## 5. Coding — one addition to §4 of the brief

**SNOMED CT UK** — free for UK use via NHS TRUD: open a TRUD account, accept the
UK licence and the SNOMED International Affiliate Licence. Distribution outside
the UK requires an Affiliate licence in that territory. Practical consequence:
the repository stores **codes**, never the terminology release files. Any
SNOMED-derived lookup table we build is a derivative and must not be committed.

**ICD-10** — as the brief mandates. Worth knowing that **ICD-11 is licensed CC
BY-ND 3.0 IGO**, has a free WHO REST/FHIR API, and its licence explicitly
contemplates clinical decision support. Since the brief's own argument is that
retrofitting coding is miserable, carrying an optional `icd11` field alongside
`icd10` costs nothing now and saves the same misery later. The ND term means we
must not adapt WHO's wording — same pattern as NICE.

**ICPC-2 — my one addition to the brief's coding requirement.** ICPC-2 (WONCA) is
the classification built for primary care, and it is the coding system in which
the best primary-care epidemiology is expressed, including the Transition Project.
SNOMED CT and ICD-10 are both shaped by secondary care. If the knowledge base
carries only SNOMED and ICD-10, every join back to the primary-care literature
goes through a lossy mapping that someone has to maintain by hand.

**Recommend adding an optional `icpc2` field to the condition and to the
presenting-complaint (reason-for-encounter) schema.** It is one nullable string.
It is the difference between being able to use the primary-care evidence base
directly and being able to use it only through a translation layer.

---

## 6. Amendments to the Phase 0 architecture position

Three, all in §5 and §7 of that document.

1. **Source hierarchy changes.** Reusable clinical content comes from NICE
   guidelines (NG/CG/QS) under the open content licence, plus open-access
   literature via PMC with verified per-article licences. CKS is read-and-link
   only, enforced by a validator lint on the `cks.nice.org.uk` domain.
2. **Schema gains three fields:** `provenance.licence` (machine-verified against
   the source record), `icpc2` on conditions and complaints, and optional
   `icd11`. NICE recommendations are stored **verbatim with attribution**, never
   paraphrased, and rules reference them by id rather than restating them.
3. **Open question 4 (regulatory) widens.** It now covers two questions for the
   same specialist: the UK MDR classification, *and* whether this constitutes an
   "AI purpose" under NICE terms clause 18.3 requiring a separate licence.

One new blocking question, added to §7 as item 7:

> **7. Transition Project data.** Its website is returning 503 and the canonical
> distribution was a CD-ROM. Do we have, or can we obtain, this dataset? A
> meaningful part of the authoring plan for complaints 2 and 3 depends on it, and
> the fallback — assembling equivalent numbers paper by paper from PMC — is
> substantially more work.

---

## Sources

- [NICE terms and conditions](https://www.nice.org.uk/terms-and-conditions) — clauses 18.1–18.9
- [NICE UK open content licence](https://www.nice.org.uk/reusing-our-content/nice-uk-open-content-licence)
- [Reusing our content | NICE](https://www.nice.org.uk/reusing-our-content)
- [NICE syndication API](https://www.nice.org.uk/reusing-our-content/nice-syndication-api)
- [NICE NG12, recommendations organised by site of cancer](https://www.nice.org.uk/guidance/ng12/chapter/recommendations-organised-by-site-of-cancer)
- [NHS website developer portal](https://developer.api.nhs.uk/)
- [NHS Website Content API v2 — NHS England Digital](https://digital.nhs.uk/developer/api-catalogue/nhs-website-content/v2)
- [NHS Website Syndicated Content: Standard Licence Terms](https://developer.api.nhs.uk/documents/NHS.UK%20Syndication%20Terms%2030-11-22.pdf)
- `https://www.nhs.uk/robots.txt`, `https://www.nice.org.uk/robots.txt`, `https://www.mayoclinic.org/robots.txt` (retrieved 2026-08-30)
- [SNOMED CT UK Clinical Edition — NHS TRUD](https://isd.digital.nhs.uk/trud/users/guest/filters/2/categories/26/items/101/licences)
- [ICD-11 licence, WHO](https://icd.who.int/en/docs/icd11-license.pdf) and [ICD-11 terms of use](https://www.who.int/publications/m/item/icd-11-terms-of-use-and-license-agreement)
- [NCBI E-utilities](https://eutils.ncbi.nlm.nih.gov/entrez/eutils/) — esearch/efetch against `db=pmc`, tested live
- [Headache in General Practice: Frequency, Management, and Results of Encounter](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4897548/) — used to verify PMC licence metadata
- [Chest pain in general practice: incidence, comorbidity and mortality](https://pubmed.ncbi.nlm.nih.gov/16461444/)
- [Chest pain in primary care: epidemiology and pre-work-up probabilities](https://www.tandfonline.com/doi/full/10.3109/13814780903329528) (paywalled)
- [Accuracy of symptoms and signs for coronary heart disease assessed in primary care | BJGP](https://bjgp.org/content/60/575/e246) (paywalled)
- [RCGP Research and Surveillance Centre public health data](https://www.rcgp.org.uk/clinical-and-research/our-programmes/research-and-surveillance-centre/public-health-data)
- [RCGP RSC Annual Report 2014–2015 | BJGP](https://bjgp.org/content/67/654/e29)
- `https://transitieproject.nl/` — HTTP 503 at time of check
