# Source catalogue

Every external source the project depends on, what it supplies, and what stops
us using it today. Status is what was verified, not what was assumed; where a
claim is untested it says so.

Verified 2026-08-31 against a live run of the fetchers.

## Working now

| Source | Supplies | Licence | Access | Status |
|---|---|---|---|---|
| **NHS TRUD** item 101, SNOMED CT UK Clinical Edition RF2 | Concept ids, the is-a poset, SNOMED to ICD-10 map | ICD-10, OPCS and UKTC SNOMED CT licences, accepted | `scripts/trud_snomed.py`, API key in `.env` | Subscribed. 977 MB release cached, 677,070 is-a edges over 416,389 concepts |
| **nice.org.uk** guidance pages | The rules themselves, quoted verbatim | NICE UK Open Content Licence — **but see the open question below** | `scripts/fetch_nice.py` | 13 guidelines cached, 19 rules encoded, all quotes machine-verified |
| **PubMed Central** open-access subset | Clinical prediction rules and likelihood ratios | CC BY per article, checked at fetch time | `scripts/fetch_pmc.py`, E-utilities, no key | Working. Ottawa SAH rule encoded from PMC8373882 |

TRUD's licence permits storing **codes**, never release files or derived
terminology tables. The archive lives in `.workbench/`, which is gitignored.

`fetch_pmc.py` refuses any article without a Creative Commons licence. Free to
read and licensed to redistribute are different things, and an Elsevier paper
was correctly rejected on that basis.

## Blocked on a credential

| Source | Supplies | Licence | Blocker |
|---|---|---|---|
| **NHS website content API** (`developer.api.nhs.uk`) | Condition and symptom coverage, safety-netting text | Open Government Licence | Developer account never confirmed to exist |
| **WHO ICD-11 API** (`icd.who.int`) | ICD-11 codes, 0 of 43 today | CC BY-ND 3.0 IGO | Registered; needs the email confirmation, then a client for the ID and secret |
| **NICE syndication API** | The same guidance, under an explicit AI licence | Negotiated | Application submitted, awaiting reply |

The NHS website content API is the licensed answer to "we want a
comprehensive symptom list per condition". It is the same shape of content as
the consumer medical sites, UK, and reusable. One registration unlocks it.

## Rejected, with the reason

| Source | Why not |
|---|---|
| **Mayo Clinic** | Blocked at the edge: `403` on `robots.txt` itself. No reuse licence. And prose symptom lists give presence, never the discriminating value or what argues against |
| **NICE CKS** (`cks.nice.org.uk`) | Read and link only. Enforced in code: `FORBIDDEN_SOURCE_HOSTS` in `kb.py` rejects any source url containing the host. API licensed through Agilio |
| **Wikidata, HPO, Orphanet** | Tested with numbers in `phase-0-acquisition-plan.md` §2. Rare-disease biased, thin on common presentations |
| **UpToDate, BMJ Best Practice** | Subscription, no redistribution. Usable as a human reference, not as a pipeline |

## Not yet investigated

- **ICPC-2**, the primary-care classification the source investigation
  recommended. Licensed through WONCA. Whether TRUD carries it is **unverified**
  — a guessed catalogue URL returned 404 and it was not chased further.
- **BNF and BNF for Children**, through Pharmaceutical Press. Not needed until
  the tool says anything about drugs.

## The open question

NICE's own application page states that using AI on NICE content is not covered
by the UK Open Content Licence and requires a licence through the NICE API.
The 13 cached guidelines and 19 encoded rules were built before that was
noticed. This is retrospective, not only forward-looking, and only NICE can
resolve it. The syndication application is in; if it stalls, ask them directly.
