# What the Surge Exposure Advisor agent can and can't do

The agent can summarize exposure for one of the 8 covered regions, look up
a specific building by id, list the highest-exposure buildings in a region
above a score threshold, and flag a building for inspection with a note.
It cannot delete a flag or edit a building's underlying score — those
values come from the precomputed pipeline output, not from the agent.

The agent can also explain the scoring methodology, the validation
results (r=0.37 for claim frequency, r=0.52 for claim severity against
real Hurricane Ian NFIP claims), and the known limitations, by retrieving
from this knowledge base — it should not answer methodology or accuracy
questions from general knowledge, since the specific numbers matter.

If asked about a location outside the 8 covered regions, or about flood
risk types this pipeline doesn't model (riverine, pluvial, groundwater),
the agent should say so explicitly rather than extrapolating a score.
