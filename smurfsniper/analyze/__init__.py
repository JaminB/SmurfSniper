"""Pure analysis over typed models (no Qt, no HTTP, no database).

Modules: ``history`` (rating points, outcomes, records, trend, sparkline), ``smurf``
(graded smurf score), ``h2h`` (head-to-head), ``intel`` (external lookup gating),
``matches`` (recent results), ``team`` (2v2+ summary).
"""

from smurfsniper.analyze.smurf import LEVELS, SmurfAssessment, SmurfInputs, assess

__all__ = ["LEVELS", "SmurfAssessment", "SmurfInputs", "assess"]
