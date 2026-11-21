"""Settings of the released font. The batch tools (batch.py, lint.py, build_font.py, audit_font.py) call
apply() before importing the stencil package, so that a plain run reproduces the release; the study tools
(proto_*.py) do not, and keep taking their options from --opts.
Override with the environment: STENCIL_OPTS=<options> (an empty string gives the cut builders' base
behaviour), STENCIL_ENGINE=bridges for the cuts of the first release (v1.000)."""
import os

VERSION = '1.100'
# the options of stencil/corners.py adopted in review rounds 10-18 (docs/09_revision_policy.md, section 3)
RELEASE_OPTS = 'scale,oblique=1.0,tip,dot,axis=0.35,kinkface,root,flat,bend=0.6,fin,band,orphan=1.0,heal=12'


def apply():
    os.environ.setdefault('STENCIL_OPTS', RELEASE_OPTS)
