"""A judged Report value for the presenters' tests: an introduced rule
finding, an existing judged one, an exempt one, a removed one, a notice,
coverage and an abstention -- and author-controlled text that addresses
each surface (ANSI escapes, control and bidi characters, a workflow
command, markdown, HTML, and the URLs, hosts, emails and mentions GFM
links by itself), as a hostile repository would write it.
"""

from __future__ import annotations

from adherence.domain.coverage import Coverage
from adherence.domain.finding import Evidence, Finding, Notice, Provenance
from adherence.domain.model import Layer, Unit, UnitKind
from adherence.domain.qualities import CheckKind, catalog_check
from adherence.domain.questions import Abstention
from adherence.domain.report import Recorded, Report, Verdict

RULES = "src/app/domain/rules.py"
# An offending line that tries to recolour the terminal, rewrite the line it
# is on, reorder it, start a workflow command on a line of its own, and
# have the job summary link a URL, a host, an email or a user by itself.
HOSTILE = (
    "x = 1\x1b[31m\x1b]0;owned\x07\r\n::error::forged‮<b>|*_[a](b)"
    " https://evil.example/x HTTP://EVIL/x ftp://x.y www.evil.com/p"
    " WWW.EVIL.COM mailto:a@b.co xmpp:a@b.co a.b@c.d.com @octocat @org/team"
)
HOSTILE_PATH = "::warning::forged.py"

STUB = Finding(
    check=catalog_check("Stub"),
    unit=Unit(RULES, UnitKind.FUNCTION, "discount", 3, 4, Layer.DOMAIN),
    layer=Layer.DOMAIN,
    subject="discount",
    evidence=Evidence(RULES, 4, HOSTILE),
    provenance=Provenance.INTRODUCED,
)
DONE = Finding(
    check=catalog_check("Done"),
    unit=Unit(RULES, UnitKind.FUNCTION, "tidy", 7, 9, Layer.DOMAIN),
    layer=Layer.DOMAIN,
    subject="tidy",
    evidence=Evidence(RULES, 8, "return order"),
    kind=CheckKind.JUDGED,
    confidence=0.93,
    provenance=Provenance.EXISTING,
)
EXEMPT = Finding(
    check=catalog_check("Grep"),
    unit=Unit(RULES, UnitKind.FILE, None, 1, 12, Layer.DOMAIN),
    layer=Layer.DOMAIN,
    subject="os",
    evidence=Evidence(RULES, 1, "import os"),
    reached=Layer.ADAPTERS,
    provenance=Provenance.EXISTING,
    exempt="the owner's reason <i>here</i>",
)
REMOVED = Finding(
    check=catalog_check("Stub"),
    unit=Unit(RULES, UnitKind.FUNCTION, "total", 10, 11, Layer.DOMAIN),
    layer=Layer.DOMAIN,
    subject="total",
    evidence=Evidence(RULES, 11, "pass"),
    provenance=Provenance.EXISTING,
)
ABSTAINED = Abstention(
    check=catalog_check("Two jobs"),
    unit=Unit(RULES, UnitKind.FILE, None, 1, 12, Layer.DOMAIN),
    layer=Layer.DOMAIN,
    question="two_jobs",
    subject=RULES,
    confidence=0.6,
)
REPORT = Report(
    ran=(catalog_check("Stub"), catalog_check("Done"), catalog_check("Grep")),
    findings=(STUB, DONE, EXEMPT),
    notices=(Notice("adherence.toml: an exemption the change adds is inert"),),
    coverage=(
        Coverage("did not finish before the deadline", check="Complexity"),
        Coverage("a symbolic link\x1b[2K", path=HOSTILE_PATH),
    ),
    abstentions=(ABSTAINED,),
    verdict=Verdict.LOWERED,
    reasons=("Stub on src/app/domain/rules.py introduced",),
    removed=(REMOVED,),
)
NOT_KEPT = Recorded(kept=False, notice=Notice("the report was not kept: disk full"))
