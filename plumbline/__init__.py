"""Check that a project's documentation still describes the project.

A README is a list of assertions: this file is here, that command works, this
variable is read. The assertions are never run, so they rot quietly, and the
first person to find out is whoever is following them under pressure.
"""

from .claims import Claim, Kind, Result, Source, Status
from .document import Document, read
from .extract import from_document
from .project import Project, scan
from .verify import verify

__all__ = ["Claim", "Document", "Kind", "Project", "Result", "Source", "Status",
           "from_document", "read", "scan", "verify"]
__version__ = "0.1.0"
