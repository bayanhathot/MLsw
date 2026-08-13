"""The consolidated AI-DJ pipeline: VibeUnderstander -> CandidateRetriever ->
SegmentSelector -> TransitionPlanner -> AudioRenderer.

Every stage is one interface in `interfaces.py` with one or more
implementations elsewhere in this package, bound via the Depends() providers
in `dependencies.py`. See Project/README.md for the full write-up.
"""
