"""The mined symptom dataset, as a script.

The same content as notebooks/dataset.ipynb. PyCharm Community cannot
render a notebook, so this is the version it can run: right-click and
Run, or step through the "# %%" cells.
"""

# # dx-navigator: the mined symptom dataset
# 
# 459 NHS condition pages, scraped for their symptom sections, with every
# wording collapsed into one canonical vocabulary by embedding cosine.
# 
# Nothing here is clinically reviewed. It is a scrape plus a language model,
# and the weights are corpus statistics, not published figures.

# %%

import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Works whether the kernel starts in the repo root or in notebooks/.
ROOT = next(p for p in (Path.cwd(), *Path.cwd().parents)
            if (p / 'scripts' / 'dataset.py').exists())
sys.path.insert(0, str(ROOT / 'scripts'))

from dataset import frames

pd.set_option('display.width', 140)
pd.set_option('display.max_colwidth', 90)

d = frames()
{k: v.shape for k, v in d.items()}

# ## conditions
# 
# One row per condition. `symptoms` holds the list, rarest first, so the head
# of each list is the symptom that most nearly names the condition.

# %%

conditions = d['conditions']
conditions[conditions.n_symptoms > 0][['name', 'system', 'n_symptoms', 'symptoms']].head(15)

# %%

# Look one up.
conditions.set_index('slug').loc['lung-cancer', 'symptoms']

# ## symptoms
# 
# The canonical vocabulary. `idf` is inverse document frequency: high means
# few conditions list it, so hearing it narrows things a lot.
# 
# This is the closest thing here to a likelihood ratio, and it is not one. It
# says how rare a word is in this corpus, not how much the symptom shifts the
# odds of a disease in a real population.

# %%

symptoms = d['symptoms']
pd.concat([
    symptoms.nsmallest(10, 'idf').assign(kind='says least'),
    symptoms[symptoms.n_conditions > 1].nlargest(10, 'idf').assign(kind='says most'),
])[['canonical', 'n_conditions', 'idf', 'kind']]

# ## How thin is the data?
# 
# The honest answer to whether any of this can work.

# %%

fig, ax = plt.subplots(1, 2, figsize=(11, 3.5))

conditions[conditions.n_symptoms > 0].n_symptoms.plot.hist(
    bins=30, ax=ax[0], color='#4a6fa5')
ax[0].set_title('symptoms per condition')
ax[0].set_xlabel('symptoms')

symptoms.n_conditions.plot.hist(bins=40, ax=ax[1], log=True, color='#a5744a')
ax[1].set_title('conditions per symptom (log count)')
ax[1].set_xlabel('conditions')

plt.tight_layout()
plt.show()

print(f"{(conditions.n_symptoms == 0).sum()} conditions have no symptoms at all")
print(f"{(symptoms.n_conditions == 1).sum()} of {len(symptoms)} symptoms appear in exactly one condition")

# A symptom that appears in exactly one condition cannot be compared against
# anything. It identifies that condition and is silent about every other. The
# count above is the share of the vocabulary doing no discriminating work.

# ## The matrix
# 
# Conditions by symptoms, 0/1. This is what the scorer sees.

# %%

m = d['matrix']
print(f'{m.shape[0]} conditions x {m.shape[1]} symptoms, {m.to_numpy().mean():.2%} filled')
m.loc[['lung-cancer', 'asthma', 'pneumonia'],
      m.loc[['lung-cancer', 'asthma', 'pneumonia']].any()].T.head(20)

# ## Which conditions look alike?
# 
# Cosine between conditions in idf-weighted symptom space. Pairs near 1 are the
# ones the tool will struggle to tell apart, because on this data they are the
# same thing.

# %%

idf = symptoms.set_index('canonical').loc[m.columns, 'idf'].to_numpy()
w = m.to_numpy() * idf
unit = w / np.linalg.norm(w, axis=1, keepdims=True)
sim = unit @ unit.T
np.fill_diagonal(sim, 0)

i, j = np.triu_indices_from(sim, k=1)
pairs = (pd.DataFrame({'a': m.index[i], 'b': m.index[j], 'cosine': sim[i, j]})
         .nlargest(20, 'cosine')
         .reset_index(drop=True))
pairs

# ## Search it
# 
# Free text in, ranked conditions out. This calls Gemini, so it needs
# `GEMINI_API_KEY` in the environment.
# 
# No prior is applied. A rare disease that matches the words ranks above a
# common one that matches slightly fewer, which is not how a GP should think
# and is the largest single thing missing from this dataset.

# %%

from triage_poc import Corpus, extract

c = Corpus()
c.set_alpha(0.25)

def search(text, n=10):
    matched = c.match(extract(text))
    ev = {sid: 1 for sid, _, _ in matched}
    scores = c.rank(ev)
    top = np.argsort(-scores)[:n]
    print('matched:', ', '.join(f'{p!r} -> {c.names[s]}' for s, p, _ in matched) or 'nothing')
    return pd.DataFrame({
        'condition': [c.display.get(c.conds[i], c.conds[i]) for i in top],
        'score': scores[top],
    })

search('dry cough for two months, coughing up blood, losing weight without trying')

# %%

search('sudden crushing chest pain spreading to my left arm, sweating, feeling sick')

# ## What is wrong with this data
# 
# Worth reading before trusting any ranking above.
# 
# - **No prevalence.** Nothing knows a cold is commoner than lung cancer.
# - **Umbrella pages rank as diagnoses.** `Cancer` is an NHS hub page, not
#   something a GP diagnoses, but it scores like a condition.
# - **A fifth of conditions are never retrieved.** In the held-out check the
#   right answer failed to reach the top ten in about 20% of cases, and
#   questioning cannot rescue what retrieval missed.
# - **53 conditions have no symptoms.** Some genuinely have none (high
#   cholesterol); others are pages the scraper could not read.
# - **Severity is absent.** Nothing marks which symptoms mean 'send to hospital
#   now'.

# %%

conditions[conditions.n_symptoms == 0][['slug', 'name', 'system']].head(20)

