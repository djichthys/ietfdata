# Copyright (C) 2017-2020 University of Glasgow
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

# The module contains code to interact with the IETF Datatracker
# (https://datatracker.ietf.org/release/about)
#
# The Datatracker API is at https://datatracker.ietf.org/api/v1 and is
# a REST API implemented using Django Tastypie (http://tastypieapi.org)
#
# It's possible to do time range queries on many of these values, for example:
#   https://datatracker.ietf.org/api/v1/person/person/?time__gt=2018-03-27T14:07:36
#
# See also:
#   https://datatracker.ietf.org/api/
#   https://trac.tools.ietf.org/tools/ietfdb/wiki/DatabaseSchemaDescription
#   https://trac.tools.ietf.org/tools/ietfdb/wiki/DatatrackerDrafts
#   RFC 6174 "Definition of IETF Working Group Document States"
#   RFC 6175 "Requirements to Extend the Datatracker for IETF Working Group Chairs and Authors"
#   RFC 6292 "Requirements for a Working Group Charter Tool"
#   RFC 6293 "Requirements for Internet-Draft Tracking by the IETF Community in the Datatracker"
#   RFC 6322 "Datatracker States and Annotations for the IAB, IRTF, and Independent Submission Streams"
#   RFC 6359 "Datatracker Extensions to Include IANA and RFC Editor Processing Information"
#   RFC 7760 "Statement of Work for Extensions to the IETF Datatracker for Author Statistics"

from datetime    import datetime, timedelta
from enum        import Enum
from typing      import List, Optional, Tuple, Dict, Iterator, Type, TypeVar, Any
from dataclasses import dataclass, field
from pathlib     import Path
from pavlova     import Pavlova
from pavlova.parsers import GenericParser

import ast
import glob
import json
import requests
import re
import sys
import time

# =================================================================================================================================
# Classes to represent the JSON-serialised objects returned by the Datatracker API:

# ---------------------------------------------------------------------------------------------------------------------------------
# URI types:

@dataclass(frozen=True)
class URI:
    uri    : str
    params : Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/document/")


@dataclass(frozen=True)
class GroupURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/group/")


# ---------------------------------------------------------------------------------------------------------------------------------
# Resource type

@dataclass(frozen=True)
class Resource:
    resource_uri : URI

T = TypeVar('T', bound=Resource)


# ---------------------------------------------------------------------------------------------------------------------------------
# Types relating to people:

@dataclass(frozen=True)
class PersonURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/person/person/") or self.uri.startswith("/api/v1/person/historicalperson/")


@dataclass(frozen=True)
class Person(Resource):
    resource_uri    : PersonURI
    id              : int
    name            : str
    name_from_draft : str
    ascii           : str
    ascii_short     : Optional[str]
    user            : str
    time            : datetime
    photo           : str
    photo_thumb     : str
    biography       : str
    consent         : bool


@dataclass(frozen=True)
class HistoricalPerson(Person):
    history_change_reason : Optional[str]
    history_user          : Optional[str]
    history_id            : int
    history_type          : str
    history_date          : datetime


@dataclass(frozen=True)
class PersonAliasURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/person/alias/")


@dataclass(frozen=True)
class PersonAlias(Resource):
    id                 : int
    resource_uri       : PersonAliasURI
    person             : PersonURI
    name               : str


@dataclass(frozen=True)
class PersonEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/person/personevent/")


@dataclass(frozen=True)
class PersonEvent(Resource):
    desc            : str
    id              : int
    person          : PersonURI
    resource_uri    : PersonEventURI
    time            : datetime
    type            : str


# ---------------------------------------------------------------------------------------------------------------------------------
# Types relating to email addresses:

@dataclass(frozen=True)
class EmailURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/person/email/") or self.uri.startswith("/api/v1/person/historicalemail/")


@dataclass(frozen=True)
class Email(Resource):
    resource_uri : EmailURI
    person       : PersonURI
    address      : str # The email address
    time         : datetime
    origin       : str
    primary      : bool
    active       : bool


@dataclass(frozen=True)
class HistoricalEmail(Email):
    history_change_reason : Optional[str]
    history_user          : Optional[str]
    history_id            : int
    history_type          : str
    history_date          : datetime


# ---------------------------------------------------------------------------------------------------------------------------------
# Types relating to documents:

@dataclass(frozen=True)
class DocumentTypeURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/doctypename/")


@dataclass(frozen=True)
class DocumentType(Resource):
    resource_uri : DocumentTypeURI
    name         : str
    used         : bool
    prefix       : str
    slug         : str
    desc         : str
    order        : int


@dataclass(frozen=True)
class DocumentStateTypeURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/statetype/")


@dataclass(frozen=True)
class DocumentStateType(Resource):
    resource_uri : DocumentStateTypeURI
    label        : str
    slug         : str


@dataclass(frozen=True)
class DocumentStateURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/state/")


@dataclass(frozen=True)
class DocumentState(Resource):
    id           : int
    resource_uri : DocumentStateURI
    desc         : str
    name         : str
    next_states  : List[DocumentStateURI]
    order        : int
    slug         : str  # FIXME: should we introduce a StateSlug type (and similar for the other slug fields)?
    type         : DocumentStateTypeURI
    used         : bool


@dataclass(frozen=True)
class StreamURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/streamname/")


@dataclass(frozen=True)
class Stream(Resource):
    resource_uri : StreamURI
    name         : str
    desc         : str
    used         : bool
    slug         : str
    order        : int


@dataclass(frozen=True)
class SubmissionURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/submit/submission/")


@dataclass(frozen=True)
class SubmissionCheckURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/submit/submissioncheck/")


@dataclass(frozen=True)
class Submission(Resource):
    abstract        : str
    access_key      : str
    auth_key        : str
    authors         : str   # See the parse_authors() method
    checks          : List[SubmissionCheckURI]
    document_date   : str   # FIXME: this should be a date object
    draft           : DocumentURI
    file_size       : Optional[int]
    file_types      : str   # e.g., ".txt,.xml"
    first_two_pages : str
    group           : Optional[GroupURI]
    id              : int
    name            : str
    note            : str
    pages           : Optional[int]
    remote_ip       : str
    replaces        : str   # This is a comma separated list of draft names (e.g., "draft-dkg-hrpc-glossary,draft-varon-hrpc-methodology")
                            # although in most cases there is only one entry, and hence no comma.
    resource_uri    : SubmissionURI
    rev             : str
    state           : str   # FIXME: this should be a URI subtype
    submission_date : str   # FIXME: this should be a date object
    submitter       : str
    title           : str
    words           : Optional[int]

    """
    URLs from which this submission can be downloaded.
    """
    def urls(self) -> Iterator[Tuple[str, str]]:
        for file_type in self.file_types.split(","):
            yield (file_type, "https://www.ietf.org/archive/id/"  + self.name + "-" + self.rev + file_type)

    def parse_authors(self) -> List[Dict[str,str]]:
        authors = ast.literal_eval(self.authors) # type: List[Dict[str, str]]
        return authors


@dataclass(frozen=True)
class SubmissionEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/submit/submissionevent/")


@dataclass(frozen=True)
class SubmissionEvent(Resource):
    by              : Optional[PersonURI]
    desc            : str
    id              : int
    resource_uri    : SubmissionEventURI
    submission      : SubmissionURI
    time            : datetime


# DocumentURI is defined earlier, to avoid circular dependencies

@dataclass(frozen=True)
class Document(Resource):
    id                 : int
    resource_uri       : DocumentURI
    name               : str
    title              : str
    pages              : Optional[int]
    words              : Optional[int]
    time               : datetime
    notify             : str
    expires            : Optional[str]
    type               : DocumentTypeURI
    rfc                : Optional[int]
    rev                : str           # If `rfc` is not None, `rev` will point to the RFC publication notice
    abstract           : str
    internal_comments  : str
    order              : int
    note               : str
    ad                 : Optional[PersonURI]
    shepherd           : Optional[EmailURI]
    group              : Optional[GroupURI]
    stream             : Optional[StreamURI]
    intended_std_level : Optional[str]  # FIXME: should be a URI subtype?
    std_level          : Optional[str]  # FIXME: should be a URI subtype?
    states             : List[DocumentStateURI]
    submissions        : List[SubmissionURI]
    tags               : List[str]
    uploaded_filename  : str
    external_url       : str

    def __post_init__(self) -> None:
        assert self.intended_std_level is None or self.intended_std_level.startswith("/api/v1/name/intendedstdlevelname/")
        assert self.std_level          is None or self.std_level.startswith("/api/v1/name/stdlevelname/")

    def url(self) -> str:
        # See https://trac.tools.ietf.org/tools/ietfdb/browser/trunk/ietf/settings.py and search for DOC_HREFS
        if self.type == DocumentTypeURI("/api/v1/name/doctypename/agenda/"):
            # FIXME: should be "/meeting/{meeting.number}/materials/{doc.name}-{doc.rev}" ???
            # FIXME: This doesn't work for interim meetings
            # FIXME: This doesn't work for PDF agenda files
            mtg = self.name.split("-")[1]
            url = "https://datatracker.ietf.org/meeting/" + mtg + "/materials/" + self.uploaded_filename
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/bluesheets/"):
            # FIXME: should be "https://www.ietf.org/proceedings/{meeting.number}/bluesheets/{doc.uploaded_filename}" ???
            mtg = self.name.split("-")[1]
            url = "https://www.ietf.org/proceedings/" + mtg + "/bluesheets/" + self.uploaded_filename
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/charter/"):
            url = "https://www.ietf.org/charter/"     + self.name + "-" + self.rev + ".txt"
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/conflrev/"):
            url = "https://www.ietf.org/cr/"          + self.name + "-" + self.rev + ".txt"
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/draft/"):
            url = "https://www.ietf.org/archive/id/"  + self.name + "-" + self.rev + ".txt"
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/liaison/"):
            url = "https://www.ietf.org/lib/dt/documents/LIAISON/" + self.uploaded_filename
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/liai-att/"):
            url = "https://www.ietf.org/lib/dt/documents/LIAISON/" + self.uploaded_filename
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/minutes/"):
            # FIXME: should be "/meeting/{meeting.number}/materials/{doc.name}-{doc.rev}" ???
            mtg = self.name.split("-")[1]
            url = "https://datatracker.ietf.org/meeting/" + mtg + "/materials/" + self.uploaded_filename
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/recording/"):
            url = self.external_url
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/review/"):
            # FIXME: This points to the formatted HTML page containing the message, but we really want the raw message
            url = "https://datatracker.ietf.org/doc/" + self.name
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/shepwrit/"):
            url = self.external_url
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/slides/"):
            # FIXME: should be https://www.ietf.org/slides/{doc.name}-{doc.rev} ???
            mtg = self.name.split("-")[1]
            url = "https://www.ietf.org/proceedings/" + mtg + "/slides/" + self.uploaded_filename
        elif self.type == DocumentTypeURI("/api/v1/name/doctypename/statchg/"):
            url = "https://www.ietf.org/sc/"          + self.name + "-" + self.rev + ".txt"
        else:
            raise NotImplementedError
        return url


@dataclass(frozen=True)
class DocumentAliasURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/docalias/")


@dataclass(frozen=True)
class DocumentAlias(Resource):
    id           : int
    resource_uri : DocumentAliasURI
    document     : DocumentURI
    name         : str


@dataclass(frozen=True)
class DocumentEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/docevent/")


@dataclass(frozen=True)
class DocumentEvent(Resource):
    by              : PersonURI
    desc            : str
    doc             : DocumentURI
    id              : int
    resource_uri    : DocumentEventURI
    rev             : str
    time            : datetime
    type            : str


@dataclass(frozen=True)
class BallotPositionNameURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/ballotpositionname/")


@dataclass(frozen=True)
class BallotPositionName(Resource):
    blocking     : bool
    desc         : Optional[str]
    name         : str
    order        : int
    resource_uri : BallotPositionNameURI
    slug         : str
    used         : bool


@dataclass(frozen=True)
class BallotTypeURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/ballottype/")


@dataclass(frozen=True)
class BallotType(Resource):
    doc_type     : DocumentTypeURI
    id           : int
    name         : str
    order        : int
    positions    : List[BallotPositionNameURI]
    question     : str
    resource_uri : BallotTypeURI
    slug         : str
    used         : bool


@dataclass(frozen=True)
class BallotDocumentEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/ballotdocevent/")


@dataclass(frozen=True)
class BallotDocumentEvent(Resource):
    ballot_type     : BallotTypeURI
    by              : PersonURI
    desc            : str
    doc             : DocumentURI
    docevent_ptr    : DocumentEventURI
    id              : int
    resource_uri    : BallotDocumentEventURI
    rev             : str
    time            : datetime
    type            : str


@dataclass(frozen=True)
class RelationshipTypeURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/docrelationshipname/")


@dataclass(frozen=True)
class RelationshipType(Resource):
    resource_uri   : RelationshipTypeURI
    slug           : str
    desc           : str
    name           : str
    used           : bool
    order          : int
    revname        : str


@dataclass(frozen=True)
class RelatedDocumentURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/relateddocument/")


@dataclass(frozen=True)
class RelatedDocument(Resource):
    id              : int
    relationship    : RelationshipTypeURI
    resource_uri    : RelatedDocumentURI
    source          : DocumentURI
    target          : DocumentAliasURI


class DocumentAuthorURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/doc/documentauthor/")


@dataclass(frozen=True)
class DocumentAuthor(Resource):
    id           : int
    order        : int
    resource_uri : DocumentAuthorURI
    country      : str
    affiliation  : str
    document     : DocumentURI
    person       : PersonURI
    email        : Optional[EmailURI]


    def normalise_country(self) -> str:
        """
        The country field of a DocumentAuthor is supposed to contain a country.
        Often it contains other things. This method tries to normalise it to a
        consistent country name.
        """
        # Does it contain a US state abbreviation and zip code?
        for state in ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
                      "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
                      "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
                      "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
                      "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
                      "DC"]:
            p = re.compile(state + ",? +[0-9][0-9][0-9][0-9][0-9]")
            if p.search(self.country):
                return "USA"
        # Does it contain a country name?
        for name in [
                "Algeria", "Argentina", "Austria", "Australia", "Belgium", "Brazil", 
                 "Canada", "Chile", "China", "Colombia", "Croatia", "Czech Republic",
                 "Denmark", "Egypt", "Finland", "France", "Germany", "Greece", "Hungary",
                 "Ireland", "India", "Israel", "Italy", "Japan", "Lebanon", "Luxembourg",
                 "Mauritius", "Mexico", "Morocco", "New Zealand", "Norway", "Philippines",
                 "Poland", "Portugal", "Romania", "Russia", "Saudi Arabia", "Singapore",
                 "Slovakia", "Slovenia", "Spain", "South Africa", "Switzerland", "Sweden",
                 "Syria", "Taiwan", "Thailand", "The Netherlands", "Turkey", "Ukraine",
                 "UK", "Uruguay", "USA", "United Arab Emirates"
            ]:
            if name.lower() in self.country.lower():
                return name
        # Does it contain a country synonym?
        for (synonym, name) in [
                ("Hellas",                    "Greece"),
                ("Italia",                    "Italy"),
                ("Korea",                     "South Korea"),
                ("Netherlands",               "The Netherlands"),
                ("P.R.C",                     "China"),
                ("PRC",                       "China"),
                ("REPUBLIC OF KOREA",         "South Korea"),
                ("Russian Federation",        "Russia"),
                ("Great Britain",             "UK"),
                ("U.K.",                      "UK"),
                ("United Kingdom",            "UK"),
                ("U.S.A",                     "USA"),
                ("United States",             "USA"),
            ]:
            if synonym.lower() in self.country.lower():
                return name
        # Does it contain a state, region, city, or street name?
        for (region, name) in [
                ("Auckland",                  "New Zealand"),
                ("Bangalore",                 "India"),
                ("Barcelona",                 "Spain"),
                ("Beijing",                   "China"),
                ("Bruxelles",                 "Belgium"),
                ("Frankfurt",                 "Germany"),
                ("Leuven",                    "Belgium"),
                ("Linkoping",                 "Sweden"),
                ("Madrid",                    "Spain"),
                ("Riga",                      "Latvia"),
                ("Solna",                     "Sweden"),
                ("Taipei",                    "Taiwan"),
                ("Tel Aviv",                  "Israel"),
                ("Tokyo",                     "Japan"),
                ("Toranomon 17 Mori Bldg.5F", "Japan"),
                ("750D Chai Chee",            "Singapore"),
                # Canadian cities:
                ("Mississauga, ON",           "Canada"),
                ("Ottawa",                    "Canada"),
                ("Toronto",                   "Canada"),
                ("100 Wynford Drive",         "Canada"),  # Bell Canada
                # US states:
                ("Arizona",                   "USA"),
                ("California",                "USA"),
                ("Colorado",                  "USA"),
                ("Florida",                   "USA"),
                ("Illinois",                  "USA"),
                ("Kansas",                    "USA"),
                ("Maryland",                  "USA"),
                ("Massachusetts",             "USA"),
                ("Michigan",                  "USA"),
                ("New Hampshire",             "USA"),
                ("New Jersey",                "USA"),
                ("Ohio",                      "USA"),
                ("Oregon",                    "USA"),
                ("Texas",                     "USA"),
                ("Vermont",                   "USA"),
                ("Virginia",                  "USA"),
                # US cities:
                ("Atlanta",                   "USA"),
                ("Bainbridge Island, WA",     "USA"),
                ("Bellevue, WA",              "USA"),
                ("Boulder CO" ,               "USA"),
                ("Boulder, CO",               "USA"),
                ("Boxborough, MA",            "USA"),
                ("Burlington, MA",            "USA"),
                ("Cambridge, MA",             "USA"),
                ("Campbell, CA",              "USA"),
                ("Chelmsford, MA",            "USA"),
                ("Dallas TX",                 "USA"),
                ("Dallas, TX",                "USA"),
                ("Denver, CO",                "USA"),
                ("Edison, NJ",                "USA"),
                ("Florham Park NJ",           "USA"),
                ("Ft. Meade, MD",             "USA"),
                ("Ft. Monmouth, N.J.",        "USA"),
                ("Littleton MA",              "USA"),
                ("Lowell, MA",                "USA"),
                ("Menlo Park, CA",            "USA"),
                ("Milpitas, CA",              "USA"),
                ("Mountain View, CA",         "USA"),
                ("Naperville, IL",            "USA"),
                ("New York",                  "USA"),
                ("Evanston, IL",              "USA"),
                ("Philadelphia",              "USA"),
                ("Princeton, NJ",             "USA"),
                ("Raleigh, NC",               "USA"),
                ("Redmond, WA",               "USA"),
                ("Richardson, TX",            "USA"),
                ("Salt Lake City",            "USA"),
                ("San Jose, CA",              "USA"),
                ("Santa Barbara, CA",         "USA"),
                ("Schaumburg, IL",            "USA"),
                ("Seattle, WA",               "USA"),
                ("St. Louis, MO",             "USA"),
                ("Stanford, CA",              "USA"),
                ("Sunnyvale, CA",             "USA"),
                ("Tewksbury, MA",             "USA"),
                ("Wall Township, NJ",         "USA"),
                ("Waltham, MA",               "USA"),
                # US streets:
                ("West Tasman Dr",            "USA"), # San Jose, CA, USA
                ("1700 Alma Drive",           "USA"), # Plano, TX, USA
                ("1201 Campbell",             "USA"), # Richardson, TX, USA
                ("3 Federal Street",          "USA"), # Billerica, MA, USA
                ("501 East Middlefield Road", "USA"), # Mountain View, CA, USA
                # UK countries:
                ("England",                   "UK"),
                ("Scotland",                  "UK"),
                ("Wales",                     "UK"),
                # UK counties:
                ("Berks",                     "UK"),
                ("Cambs",                     "UK"),
                ("Essex",                     "UK"),
                ("Gwent",                     "UK"),
                ("Hampshire",                 "UK"),
                ("Surrey",                    "UK"),
                ("Middlesex",                 "UK"),
                # UK cities:
                ("Aberdeen AB24",             "UK"),
                ("Cambridge",                 "UK"),
                ("Edinburgh",                 "UK"),
                ("Ipswich",                   "UK"),
                ("Maidenhead",                "UK"),
                ("Nottingham",                "UK"),
                ("Reading",                   "UK"),
                ("London",                    "UK"),
                ("Oxford",                    "UK"),
                ("Winchester",                "UK"),
            ]:
            if region.lower() in self.country.lower():
                return name
        # Does it contain an organisation name?
        for (org, name) in [
                ("Aoyama Gakuin University",          "Japan"),
                ("University of Cambridge",           "UK"),
                ("Columbia University",               "USA"),
                ("University of Illinois",            "USA"),
                ("University of Washington",          "USA"),
                ("National Security Agency",          "USA"),
                ("ICSI Center for Internet Research", "USA"),
                ("Schrage Consulting",                "Germany"),
                ("Samsung Electronics",               "South Korea"),
                ("Nishinippori Start up Office 214",  "Japan"),
            ]:
            if org.lower() in self.country.lower():
                return name
        # Does it contain a postcode?
        for (postcode, name) in [
                ("H3B 2S2",    "Canada"),        # Montréal, QC, Canada
                ("H4P 2N2",    "Canada"),        # Montréal, QC, Canada
                ("K1Y 4H7",    "Canada"),        # Ottawa, ON, Canada
                ("K1Y-4H7",    "Canada"),        # Ottawa, ON, Canada
                ("K2K 3N1",    "Canada"),        # Ottawa, ON, Canada
                ("V5H 4M2",    "Canada"),        # Burnaby, BC, Canada
                ("V7X 1M3 ",   "Canada"),        # Vancouver, BC, Canada
                ("F-22307",    "France"),        # INRIA Rennes-Bretagne Altlantique, France
                ("FIN-00076",  "Finland"),       # Aalto University
                ("CH-6942",    "Switzerland"),   # Savosa, Switzerland
                ("CB3 0FD",    "UK"),            # University of Cambridge, UK
                ("WR14 3PS",   "UK"),            # Malvern, Worcestershire, UK
                ("02144",      "USA"),           # Somerville, MA, USA
                ("02138",      "USA"),           # Cambridge, MA, USA
                ("20166",      "USA"),           # Dulles, VA, USA
                ("94704-1198", "USA"),           # Berkeley, CA, USA
                ("95110",      "USA"),           # San Jose, CA, USA
                ("Post Office Box 5005", "USA"), # Rochester, NH, USA
                ("7010",       "Belgium")        # NATO C&I Agency, SHAPE, Belgium
            ]:
            if postcode.lower() in self.country.lower():
                return name
        # Does it contain a person's name?
        for (person, name) in [
                ("Robert Schuettler", "Germany"),
                ("Mike St. Johns",    "USA"),
            ]:
            if person.lower() in self.country.lower():
                return name
        # Does it contain a country abbreviation?
        for (abbrv, name) in [
                ("AU", "Australia"),
                ("BE", "Belgium"),
                ("BR", "Brazil"),
                ("CA", "Canada"),
                ("CH", "Switzerland"),
                ("CN", "China"),
                ("CZ", "Czech Republic"),
                ("DE", "Germany"),
                ("ES", "Spain"),
                ("FI", "Finland"),
                ("FR", "France"),
                ("GE", "Germany"),
                ("GB", "UK"),
                ("GI", "UK"),           # Gibralter
                ("IE", "Ireland"),
                ("IL", "Israel"),
                ("IT", "Italy"),
                ("JA", "Japan"),
                ("JP", "Japan"),
                ("MU", "Mauritius"),
                ("NL", "The Netherlands"),
                ("NO", "Norway"),
                ("SE", "Sweden"),
                ("SG", "Singapore"),
                ("US", "USA"),
            ]:
            if abbrv.lower() in self.country.lower():
                return name
        # Does it contain something random?
        for (text, name) in [
                ("January 2002", "USA"),  # RFC3271
            ]:
            if text.lower() in self.country.lower():
                return name
        # Otherwise, just return the country unchanged:
        return self.country.strip()


    def normalise_affiliation(self) -> str:
        # FIXME: implement this
        return self.affiliation


# ---------------------------------------------------------------------------------------------------------------------------------
# Types relating to groups:


@dataclass(frozen=True)
class GroupStateURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/groupstatename/")


@dataclass(frozen=True)
class GroupState(Resource):
    resource_uri   : GroupStateURI
    slug           : str
    desc           : str
    name           : str
    used           : bool
    order          : int


@dataclass(frozen=True)
class GroupTypeNameURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/grouptypename/")


@dataclass(frozen=True)
class GroupTypeName(Resource):
    desc          : str
    name          : str
    order         : int
    resource_uri  : GroupTypeNameURI
    slug          : str
    used          : bool
    verbose_name  : str


# GroupURI is defined earlier, to avoid circular dependencies


@dataclass(frozen=True)
class Group(Resource):
    acronym        : str
    ad             : Optional[PersonURI]
    charter        : Optional[DocumentURI]
    comments       : str
    description    : str
    id             : int
    list_archive   : str
    list_email     : str
    list_subscribe : str
    name           : str
    parent         : Optional[GroupURI]
    resource_uri   : GroupURI
    state          : GroupStateURI
    time           : datetime
    type           : GroupTypeNameURI
    unused_states  : List[str]
    unused_tags    : List[str]


@dataclass(frozen=True)
class GroupHistoryURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/grouphistory/")


@dataclass(frozen=True)
class GroupHistory(Resource):
    acronym              : str
    ad                   : Optional[PersonURI]
    comments             : str
    description          : str
    group                : GroupURI
    id                   : int
    list_archive         : str
    list_email           : str
    list_subscribe       : str
    name                 : str
    parent               : Optional[GroupURI]
    resource_uri         : GroupHistoryURI
    state                : GroupStateURI
    time                 : datetime
    type                 : GroupTypeNameURI
    unused_states        : List[str]
    unused_tags          : List[str]
    uses_milestone_dates : bool


@dataclass(frozen=True)
class GroupEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/groupevent/")


@dataclass(frozen=True)
class GroupEvent(Resource):
    by           : PersonURI
    desc         : str
    group        : GroupURI
    id           : int
    resource_uri : GroupEventURI
    time         : datetime
    type         : str


@dataclass(frozen=True)
class GroupUrlURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/groupurl/")


@dataclass(frozen=True)
class GroupUrl(Resource):
    group        : GroupURI
    id           : int
    name         : str
    resource_uri : GroupUrlURI
    url          : str


@dataclass(frozen=True)
class GroupMilestoneStateNameURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/groupmilestonestatename/")


@dataclass(frozen=True)
class GroupMilestoneStateName(Resource):
    desc         : str
    name         : str
    order        : int
    resource_uri : GroupMilestoneStateNameURI
    slug         : str
    used         : bool


@dataclass(frozen=True)
class GroupMilestoneURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/groupmilestone/")


@dataclass(frozen=True)
class GroupMilestone(Resource):
    desc         : str
    docs         : List[DocumentURI]
    due          : str
    group        : GroupURI
    id           : int
    order        : Optional[int]
    resolved     : str
    resource_uri : GroupMilestoneURI
    state        : GroupMilestoneStateNameURI
    time         : datetime


@dataclass(frozen=True)
class RoleNameURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/rolename/")

@dataclass(frozen=True)
class RoleName(Resource):
    desc         : str
    name         : str
    order        : int
    resource_uri : RoleNameURI
    slug         : str
    used         : bool


@dataclass(frozen=True)
class GroupRoleURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/role/")


@dataclass(frozen=True)
class GroupRole(Resource):
    email        : EmailURI
    group        : GroupURI
    id           : int
    name         : RoleNameURI
    person       : PersonURI
    resource_uri : GroupRoleURI

@dataclass(frozen=True)
class GroupMilestoneHistoryURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/groupmilestonehistory/")


@dataclass(frozen=True)
class GroupMilestoneHistory(Resource):
    desc         : str
    docs         : List[DocumentURI]
    due          : str
    group        : GroupURI
    id           : int
    milestone    : GroupMilestoneURI
    order        : Optional[int]
    resolved     : str
    resource_uri : GroupMilestoneHistoryURI
    state        : GroupMilestoneStateNameURI
    time         : datetime


@dataclass(frozen=True)
class GroupMilestoneEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/milestonegroupevent/")


@dataclass(frozen=True)
class GroupMilestoneEvent(Resource):
    by             : PersonURI
    desc           : str
    group          : GroupURI
    groupevent_ptr : GroupEventURI
    id             : int
    milestone      : GroupMilestoneURI
    resource_uri   : GroupMilestoneEventURI
    time           : datetime
    type           : str


@dataclass(frozen=True)
class GroupRoleHistoryURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/rolehistory/")


@dataclass(frozen=True)
class GroupRoleHistory(Resource):
    email        : EmailURI
    group        : GroupHistoryURI
    id           : int
    name         : RoleNameURI
    person       : PersonURI
    resource_uri : GroupRoleHistoryURI


@dataclass(frozen=True)
class GroupStateChangeEventURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/group/changestategroupevent/")


@dataclass(frozen=True)
class GroupStateChangeEvent(Resource):
    by             : PersonURI
    desc           : str
    group          : GroupURI
    groupevent_ptr : GroupEventURI
    id             : int
    resource_uri   : GroupStateChangeEventURI
    state          : GroupStateURI
    time           : datetime
    type           : str


# ---------------------------------------------------------------------------------------------------------------------------------
# Types relating to meetings:

class MeetingStatus(Enum):
    FUTURE    = 1
    ONGOING   = 2
    COMPLETED = 3


@dataclass(frozen=True)
class MeetingURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/meeting/meeting/")


@dataclass(frozen=True)
class MeetingTypeURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/name/meetingtypename/")


@dataclass(frozen=True)
class MeetingType(Resource):
    name         : str
    order        : int
    resource_uri : MeetingTypeURI
    slug         : str
    desc         : str
    used         : bool


@dataclass(frozen=True)
class ScheduleURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/meeting/schedule/")


@dataclass(frozen=True)
class Schedule(Resource):
    """
    A particular version of the meeting schedule (i.e., the meeting agenda)

    Use `meeting_session_assignments()` to find the assignment of sessions
    to timeslots within this schedule.
    """
    id           : int
    name         : str
    resource_uri : ScheduleURI
    owner        : PersonURI
    meeting      : MeetingURI
    visible      : bool
    public       : bool
    badness      : Optional[str]


@dataclass(frozen=True)
class Meeting(Resource):
    id                               : int
    resource_uri                     : MeetingURI
    type                             : MeetingTypeURI
    country                          : str
    city                             : str
    venue_name                       : str
    venue_addr                       : str
    date                             : str  # FIXME: this should be a date object
    days                             : int  # FIXME: this should be a timedelta object
    time_zone                        : str
    acknowledgements                 : str
    agenda_info_note                 : str
    agenda_warning_note              : str
    session_request_lock_message     : str
    idsubmit_cutoff_warning_days     : str
    idsubmit_cutoff_time_utc         : str
    idsubmit_cutoff_day_offset_00    : int
    idsubmit_cutoff_day_offset_01    : int
    submission_start_day_offset      : int
    submission_cutoff_day_offset     : int
    submission_correction_day_offset : int
    agenda                           : ScheduleURI  # An alias for schedule
    schedule                         : ScheduleURI  # The current meeting schedule (i.e., the agenda)
    number                           : str
    break_area                       : str
    reg_area                         : str
    proceedings_final                : bool
    show_important_dates             : bool
    attendees                        : Optional[int]
    updated                          : datetime     # Time this record was modified

    def status(self) -> MeetingStatus:
        now = datetime.now()
        meeting_start = datetime.strptime(self.date, "%Y-%m-%d")
        meeting_end   = meeting_start + timedelta(days = self.days - 1)
        if meeting_start > now:
            return MeetingStatus.FUTURE
        elif meeting_end < now:
            return MeetingStatus.COMPLETED
        else:
            return MeetingStatus.ONGOING


@dataclass(frozen=True)
class SessionURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/meeting/session/")


@dataclass(frozen=True)
class TimeslotURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/meeting/timeslot/")


@dataclass(frozen=True)
class Timeslot(Resource):
    id            : int
    resource_uri  : TimeslotURI
    type          : str               # FIXME: this is a URI "/api/v1/name/timeslottypename/regular/"
    meeting       : MeetingURI
    sessions      : List[SessionURI]  # Sessions assigned to this slot in various versions of the agenda; current assignment is last
    name          : str
    time          : datetime
    duration      : str               # FIXME: this should be a timedelta object
    location      : str               # FIXME: this is a URI "/api/v1/meeting/room/668
    show_location : bool
    modified      : datetime


@dataclass(frozen=True)
class SessionAssignmentURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/meeting/schedtimesessassignment/")


@dataclass(frozen=True)
class SessionAssignment(Resource):
    """
    The assignment of a `session` to a `timeslot` within a meeting `schedule`
    """
    id           : int
    resource_uri : SessionAssignmentURI
    session      : SessionURI
    agenda       : ScheduleURI  # An alias for `schedule`
    schedule     : ScheduleURI
    timeslot     : TimeslotURI
    modified     : datetime
    notes        : str
    pinned       : bool
    extendedfrom : Optional[str]
    badness      : int


@dataclass(frozen=True)
class Session(Resource):
    id                  : int
    type                : str           # FIXME: this is a URI
    name                : str
    resource_uri        : SessionURI
    meeting             : MeetingURI
    group               : GroupURI
    materials           : List[DocumentURI]
    scheduled           : str          # Date scheduled
    requested_duration  : str
    resources           : List[str]    # FIXME
    agenda_note         : str
    assignments         : List[SessionAssignmentURI]
    remote_instructions : str
    short               : str
    attendees           : int
    modified            : datetime
    comments            : str


# ---------------------------------------------------------------------------------------------------------------------------------
# Types relating to mailing lists:

@dataclass(frozen=True)
class MailingListURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/mailinglists/list/")


@dataclass(frozen=True)
class MailingList(Resource):
    id           : int
    resource_uri : MailingListURI
    name         : str
    description  : str
    advertised   : bool


@dataclass(frozen=True)
class MailingListSubscriptionsURI(URI):
    def __post_init__(self) -> None:
        assert self.uri.startswith("/api/v1/mailinglists/subscribed/")


@dataclass(frozen=True)
class MailingListSubscriptions(Resource):
    id           : int
    resource_uri : MailingListSubscriptionsURI
    email        : str
    lists        : List[MailingListURI]
    time         : datetime


# =================================================================================================================================
# A class to represent the datatracker:

class DataTracker:
    """
    A class for interacting with the IETF DataTracker.
    """
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Parameters:
            cache_dir      -- If set, use this directory as a cache for Datatracker objects
        """
        self.session  = requests.Session()
        self.ua       = "glasgow-ietfdata/0.2.0"          # Update when making a new relaase
        self.base_url = "https://datatracker.ietf.org"
        self.http_req = 0
        self.cache_dir = cache_dir
        self.pavlova = Pavlova()
        # Please sort the following alphabetically:
        self.pavlova.register_parser(BallotDocumentEventURI, GenericParser(self.pavlova, BallotDocumentEventURI))
        self.pavlova.register_parser(BallotPositionNameURI,  GenericParser(self.pavlova, BallotPositionNameURI))
        self.pavlova.register_parser(BallotTypeURI,          GenericParser(self.pavlova, BallotTypeURI))
        self.pavlova.register_parser(DocumentAliasURI,       GenericParser(self.pavlova, DocumentAliasURI))
        self.pavlova.register_parser(DocumentAuthorURI,      GenericParser(self.pavlova, DocumentAuthorURI))
        self.pavlova.register_parser(DocumentEventURI,       GenericParser(self.pavlova, DocumentEventURI))
        self.pavlova.register_parser(DocumentStateURI,       GenericParser(self.pavlova, DocumentStateURI))
        self.pavlova.register_parser(DocumentStateTypeURI,   GenericParser(self.pavlova, DocumentStateTypeURI))
        self.pavlova.register_parser(DocumentTypeURI,        GenericParser(self.pavlova, DocumentTypeURI))
        self.pavlova.register_parser(DocumentURI,            GenericParser(self.pavlova, DocumentURI))
        self.pavlova.register_parser(EmailURI,               GenericParser(self.pavlova, EmailURI))
        self.pavlova.register_parser(GroupEventURI,          GenericParser(self.pavlova, GroupEventURI))
        self.pavlova.register_parser(GroupHistoryURI,        GenericParser(self.pavlova, GroupHistoryURI))
        self.pavlova.register_parser(GroupMilestoneEventURI, GenericParser(self.pavlova, GroupMilestoneEventURI))
        self.pavlova.register_parser(GroupMilestoneHistoryURI, GenericParser(self.pavlova, GroupMilestoneHistoryURI))
        self.pavlova.register_parser(GroupMilestoneStateNameURI, GenericParser(self.pavlova, GroupMilestoneStateNameURI))
        self.pavlova.register_parser(GroupMilestoneURI,      GenericParser(self.pavlova, GroupMilestoneURI))
        self.pavlova.register_parser(GroupRoleURI,           GenericParser(self.pavlova, GroupRoleURI))
        self.pavlova.register_parser(GroupRoleHistoryURI,    GenericParser(self.pavlova, GroupRoleHistoryURI))
        self.pavlova.register_parser(GroupStateChangeEventURI, GenericParser(self.pavlova, GroupStateChangeEventURI))
        self.pavlova.register_parser(GroupStateURI,          GenericParser(self.pavlova, GroupStateURI))
        self.pavlova.register_parser(GroupTypeNameURI,       GenericParser(self.pavlova, GroupTypeNameURI))
        self.pavlova.register_parser(GroupURI,               GenericParser(self.pavlova, GroupURI))
        self.pavlova.register_parser(GroupUrlURI,            GenericParser(self.pavlova, GroupUrlURI))
        self.pavlova.register_parser(MailingListURI,         GenericParser(self.pavlova, MailingListURI))
        self.pavlova.register_parser(MailingListSubscriptionsURI, GenericParser(self.pavlova, MailingListSubscriptionsURI))
        self.pavlova.register_parser(MeetingTypeURI,         GenericParser(self.pavlova, MeetingTypeURI))
        self.pavlova.register_parser(MeetingURI,             GenericParser(self.pavlova, MeetingURI))
        self.pavlova.register_parser(PersonAliasURI,         GenericParser(self.pavlova, PersonAliasURI))
        self.pavlova.register_parser(PersonEventURI,         GenericParser(self.pavlova, PersonEventURI))
        self.pavlova.register_parser(PersonURI,              GenericParser(self.pavlova, PersonURI))
        self.pavlova.register_parser(RelationshipTypeURI,    GenericParser(self.pavlova, RelationshipTypeURI))
        self.pavlova.register_parser(RelatedDocumentURI,     GenericParser(self.pavlova, RelatedDocumentURI))
        self.pavlova.register_parser(RoleNameURI,            GenericParser(self.pavlova, RoleNameURI))
        self.pavlova.register_parser(SessionAssignmentURI,   GenericParser(self.pavlova, SessionAssignmentURI))
        self.pavlova.register_parser(SessionURI,             GenericParser(self.pavlova, SessionURI))
        self.pavlova.register_parser(ScheduleURI,            GenericParser(self.pavlova, ScheduleURI))
        self.pavlova.register_parser(StreamURI,              GenericParser(self.pavlova, StreamURI))
        self.pavlova.register_parser(SubmissionCheckURI,     GenericParser(self.pavlova, SubmissionCheckURI))
        self.pavlova.register_parser(SubmissionEventURI,     GenericParser(self.pavlova, SubmissionEventURI))
        self.pavlova.register_parser(SubmissionURI,          GenericParser(self.pavlova, SubmissionURI))
        self.pavlova.register_parser(TimeslotURI,            GenericParser(self.pavlova, TimeslotURI))


    def __del__(self):
        self.session.close()


    def _cache_filepath(self, resource_uri: URI) -> Path:
        assert self.cache_dir is not None
        return Path(self.cache_dir, resource_uri.uri[1:-1] + ".json")


    def _obj_is_cached(self, resource_uri: URI) -> bool:
        if self.cache_dir is None:
            return False
        return self._cache_filepath(resource_uri).exists()


    def _retrieve_from_cache(self, resource_uri: URI) -> Dict[Any, Any]:
        obj_json = {}
        with open(self._cache_filepath(resource_uri)) as cache_file:
            obj_json = json.load(cache_file)
        return obj_json


    def _cache_obj(self, resource_uri: URI, obj_json: Dict[Any, Any]) -> None:
        if self.cache_dir is not None:
            cache_filepath = self._cache_filepath(resource_uri)
            cache_filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_filepath, "w") as cache_file:
                json.dump(obj_json, cache_file)


    def _rate_limit(self) -> None:
        # A trivial rate limiter. Called before every HTTP GET to the datatracker.
        # The datatracker objects if more than 100 requests are made on a single
        # persistent HTTP connection.
        self.http_req += 1
        if (self.http_req % 100) == 0:
            self.session.close()


    def _retrieve(self, resource_uri: URI, obj_type: Type[T]) -> Optional[T]:
        headers = {'User-Agent': self.ua}
        if self._obj_is_cached(resource_uri):
            obj_json = self._retrieve_from_cache(resource_uri)
        else:
            self._rate_limit()
            r = self.session.get(self.base_url + resource_uri.uri, params=resource_uri.params, headers=headers, verify=True, stream=False)
            if r.status_code == 200:
                obj_json = r.json()
                self._cache_obj(resource_uri, obj_json)
            elif r.status_code == 404:
                return None
            else:
                print("_retrieve failed: {} {}".format(r.status_code, self.base_url + resource_uri.uri))
                sys.exit(1)
        obj = self.pavlova.from_mapping(obj_json, obj_type) # type: T
        return obj

    def _retrieve_multi(self, resource_uri: URI, obj_type: Type[T], deref: Dict[str, str] = {}) -> Iterator[T]:
        # deref is currently unused, but will be needed for the cache
        headers = {'user-agent': self.ua}
        resource_uri.params["limit"] = "100"
        while resource_uri.uri is not None:
            self._rate_limit()
            retry = True
            retry_time = 1.875
            while retry:
                retry = False
                r = self.session.get(self.base_url + resource_uri.uri, params=resource_uri.params, headers=headers, verify=True, stream=False)
                if r.status_code == 200:
                    meta = r.json()['meta']
                    objs = r.json()['objects']
                    resource_uri  = URI(meta['next'])
                    for obj_json in objs:
                        obj = self.pavlova.from_mapping(obj_json, obj_type) # type: T
                        self._cache_obj(obj.resource_uri, obj_json)
                        yield obj
                elif r.status_code == 500:
                    if retry_time > 60:
                        print("_retrieve_multi failed: error {} after {} requests".format(r.status_code, self.http_req))
                        sys.exit(1)
                    self.session.close()
                    time.sleep(retry_time)
                    retry_time *= 2
                    retry = True
                else:
                    print("_retrieve_multi failed: error {} after {} requests".format(r.status_code, self.http_req))
                    sys.exit(1)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about people:
    # * https://datatracker.ietf.org/api/v1/person/person/
    # * https://datatracker.ietf.org/api/v1/person/person/20209/
    # * https://datatracker.ietf.org/api/v1/person/historicalperson/
    # * https://datatracker.ietf.org/api/v1/person/alias/

    def person(self, person_uri: PersonURI) -> Optional[Person]:
        return self._retrieve(person_uri, Person)


    def person_from_email(self, email_addr: str) -> Optional[Person]:
        email = self.email(EmailURI("/api/v1/person/email/" + email_addr + "/"))
        if email is not None:
            return self.person(email.person)
        else:
            return None


    def person_aliases(self, person: Person) -> Iterator[PersonAlias]:
        url = PersonAliasURI("/api/v1/person/alias/")
        url.params["person"] = str(person.id)
        return self._retrieve_multi(url, PersonAlias, deref = {"person": "id"})


    def person_history(self, person: Person) -> Iterator[HistoricalPerson]:
        url = PersonURI("/api/v1/person/historicalperson/")
        url.params["id"] = str(person.id)
        return self._retrieve_multi(url, HistoricalPerson, deref = {"person": "id"})


    def person_events(self, person: Person) -> Iterator[PersonEvent]:
        url = PersonEventURI("/api/v1/person/personevent/")
        url.params["person"] = str(person.id)
        return self._retrieve_multi(url, PersonEvent, deref = {"person": "id"})


    def people(self,
            since : str ="1970-01-01T00:00:00",
            until : str ="2038-01-19T03:14:07",
            name_contains : Optional[str] = None) -> Iterator[Person]:
        """
        A generator that returns people recorded in the datatracker. As of April
        2018, there are approximately 21500 people recorded.

        Parameters:
            since         -- Only return people with timestamp after this
            until         -- Only return people with timestamp before this
            name_contains -- Only return peopls whose name containing this string

        Returns:
            An iterator, where each element is as returned by the person() method
        """
        url = PersonURI("/api/v1/person/person/")
        url.params["time__gte"] = since
        url.params["time__lt"]  = until
        url.params["name__contains"] = name_contains
        return self._retrieve_multi(url, Person)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about email addresses:
    # * https://datatracker.ietf.org/api/v1/person/email/csp@csperkins.org/
    # * https://datatracker.ietf.org/api/v1/person/historicalemail/

    def email(self, email_uri: EmailURI) -> Optional[Email]:
        return self._retrieve(email_uri, Email)


    def email_for_person(self, person: Person) -> Iterator[Email]:
        uri = EmailURI("/api/v1/person/email/")
        uri.params["person"] = str(person.id)
        return self._retrieve_multi(uri, Email, deref = {"person": "id"})


    def email_history_for_address(self, email_addr: str) -> Iterator[HistoricalEmail]:
        uri = EmailURI("/api/v1/person/historicalemail/")
        uri.params["address"] = email_addr
        return self._retrieve_multi(uri, HistoricalEmail)


    def email_history_for_person(self, person: Person) -> Iterator[HistoricalEmail]:
        uri = EmailURI("/api/v1/person/historicalemail/")
        uri.params["person"] = person.id
        return self._retrieve_multi(uri, HistoricalEmail, deref = {"person": "id"})


    def emails(self,
               since : str ="1970-01-01T00:00:00",
               until : str ="2038-01-19T03:14:07",
               addr_contains : Optional[str] = None) -> Iterator[Email]:
        """
        A generator that returns email addresses recorded in the datatracker.

        Parameters:
            since         -- Only return email addresses with timestamp after this
            until         -- Only return email addresses with timestamp before this
            addr_contains -- Only return email addresses containing this substring

        Returns:
            An iterator, where each element is an Email object
        """
        url = EmailURI("/api/v1/person/email/")
        url.params["time__gte"] = since
        url.params["time__lt"]   = until
        url.params["address__contains"] = addr_contains
        return self._retrieve_multi(url, Email)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about documents:
    # * https://datatracker.ietf.org/api/v1/doc/document/                        - list of documents
    # * https://datatracker.ietf.org/api/v1/doc/document/draft-ietf-avt-rtp-new/ - info about document

    def document(self, document_uri: DocumentURI) -> Optional[Document]:
        return self._retrieve(document_uri, Document)


    def documents(self,
            since   : str = "1970-01-01T00:00:00",
            until   : str = "2038-01-19T03:14:07",
            doctype : Optional[DocumentType] = None,
            group   : Optional[Group]        = None) -> Iterator[Document]:
        url = DocumentURI("/api/v1/doc/document/")
        url.params["time__gt"] = since
        url.params["time__lt"] = until
        if doctype is not None:
            url.params["type"] = doctype.slug
        if group is not None:
            url.params["group"] = group.id
        return self._retrieve_multi(url, Document, deref = {"type": "slug", "group": "id"})


    # Datatracker API endpoints returning information about document aliases:
    # * https://datatracker.ietf.org/api/v1/doc/docalias/?name=/                 - draft that became the given RFC

    def document_alias(self, document_alias_uri: DocumentAliasURI) -> Optional[DocumentAlias]:
        return self._retrieve(document_alias_uri, DocumentAlias)


    def document_aliases(self, name: Optional[str] = None) -> Iterator[DocumentAlias]:
        """
        Returns a list of DocumentAlias objects that correspond to the specified name.

        Parameters:
            name -- The name to lookup, for example "rfc3550", "std68", "bcp25", "draft-ietf-quic-transport"

        Returns:
            A list of DocumentAlias objects
        """
        url = DocumentAliasURI("/api/v1/doc/docalias/")
        url.params["name"] = name
        return self._retrieve_multi(url, DocumentAlias)


    def document_from_draft(self, draft: str) -> Optional[Document]:
        """
        Returns the document with the specified name.

        Parameters:
            name -- The name of the document to lookup (e.g, "draft-ietf-avt-rtp-new")

        Returns:
            A Document object
        """
        assert draft.startswith("draft-")
        assert not "," in draft
        return self.document(DocumentURI("/api/v1/doc/document/" + draft + "/"))


    def document_from_rfc(self, rfc: str) -> Optional[Document]:
        """
        Returns the document that became the specified RFC.

        Parameters:
            rfc -- The RFC to lookup (e.g., "rfc3550" or "RFC3550")

        Returns:
            A Document object
        """
        assert rfc.lower().startswith("rfc")
        docs = list(self.document_aliases(name=rfc.lower()))
        if len(docs) == 0:
            return None
        elif len(docs) == 1:
            return self.document(docs[0].document)
        else:
            raise RuntimeError


    def documents_from_bcp(self, bcp: str) -> Iterator[Document]:
        """
        Returns the document that became the specified BCP.

        Parameters:
            bcp -- The BCP to lookup (e.g., "bcp205" or "BCP205")

        Returns:
            A list of Document objects
        """
        assert bcp.lower().startswith("bcp")
        for alias in self.document_aliases(name=bcp.lower()):
            doc = self.document(alias.document)
            if doc is not None:
                yield doc


    def documents_from_std(self, std: str) -> Iterator[Document]:
        """
        Returns the document that became the specified STD.

        Parameters:
            std -- The STD to lookup (e.g., "std68" or "STD68")

        Returns:
            A list of Document objects
        """
        assert std.lower().startswith("std")
        for alias in self.document_aliases(name=std.lower()):
            doc = self.document(alias.document)
            if doc is not None:
                yield doc


    # Datatracker API endpoints returning information about document types:
    # * https://datatracker.ietf.org/api/v1/name/doctypename/

    def document_type(self, doc_type_uri: DocumentTypeURI) -> Optional[DocumentType]:
        return self._retrieve(doc_type_uri, DocumentType)


    def document_types(self) -> Iterator[DocumentType]:
        return self._retrieve_multi(DocumentTypeURI("/api/v1/name/doctypename/"), DocumentType)


    # Datatracker API endpoints returning information about document states:
    # * https://datatracker.ietf.org/api/v1/doc/state/                           - Types of state a document can be in
    # * https://datatracker.ietf.org/api/v1/doc/statetype/                       - Possible types of state for a document

    def document_state(self, state_uri: DocumentStateURI) -> Optional[DocumentState]:
        return self._retrieve(state_uri, DocumentState)


    def document_states(self, state_type : Optional[DocumentStateType] = None) -> Iterator[DocumentState]:
        url = DocumentStateURI("/api/v1/doc/state/")
        if state_type is not None:
            url.params["type"] = state_type.slug
        return self._retrieve_multi(url, DocumentState, deref = {"type": "slug"})


    def document_state_type(self, state_type_uri : DocumentStateTypeURI) -> Optional[DocumentStateType]:
        return self._retrieve(state_type_uri, DocumentStateType)


    def document_state_types(self) -> Iterator[DocumentStateType]:
        url = DocumentStateTypeURI("/api/v1/doc/statetype/")
        return self._retrieve_multi(url, DocumentStateType)


    # Datatracker API endpoints returning information about document events:
    # * https://datatracker.ietf.org/api/v1/doc/docevent/                        - list of document events
    # * https://datatracker.ietf.org/api/v1/doc/docevent/?doc=...                - events for a document
    # * https://datatracker.ietf.org/api/v1/doc/docevent/?by=...                 - events by a person (as /api/v1/person/person)
    # * https://datatracker.ietf.org/api/v1/doc/docevent/?time=...               - events by time
    #   https://datatracker.ietf.org/api/v1/doc/statedocevent/                   - subset of /api/v1/doc/docevent/; same parameters
    #   https://datatracker.ietf.org/api/v1/doc/newrevisiondocevent/             -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/submissiondocevent/              -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/writeupdocevent/                 -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/consensusdocevent/               -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/reviewrequestdocevent/           -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/lastcalldocevent/                -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/telechatdocevent/                -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/initialreviewdocevent/           -               "                "
    #   https://datatracker.ietf.org/api/v1/doc/editedauthorsdocevent/           -               "                "

    def document_event(self, event_uri : DocumentEventURI) -> Optional[DocumentEvent]:
        return self._retrieve(event_uri, DocumentEvent)


    def document_events(self,
                        since      : str = "1970-01-01T00:00:00",
                        until      : str = "2038-01-19T03:14:07",
                        doc        : Document = None,
                        by         : Person   = None,
                        event_type : str      = None) -> Iterator[DocumentEvent]:
        """
        A generator returning information about document events.

        Parameters:
            since      -- Only return document events with timestamp after this
            until      -- Only return document events with timestamp after this
            doc        -- Only return document events for this document
            by         -- Only return document events by this person
            event_type -- Only return document events with this type

        Returns:
           A sequence of DocumentEvent objects
        """
        url = DocumentEventURI("/api/v1/doc/docevent/")
        url.params["time__gt"] = since
        url.params["time__lt"] = until
        if doc is not None:
            url.params["doc"]  = doc.id
        if by is not None:
            url.params["by"]   = by.id
        url.params["type"]     = event_type
        return self._retrieve_multi(url, DocumentEvent, deref = {"doc": "id", "by": "id"})


    # Datatracker API endpoints returning information about document authorship:
    # * https://datatracker.ietf.org/api/v1/doc/documentauthor/?document=...     - authors of a document
    # * https://datatracker.ietf.org/api/v1/doc/documentauthor/?person=...       - documents by person
    # * https://datatracker.ietf.org/api/v1/doc/documentauthor/?email=...        - documents by person

    def document_authors(self, document : Document) -> Iterator[DocumentAuthor]:
        url = DocumentAuthorURI("/api/v1/doc/documentauthor/")
        url.params["document"] = document.id
        return self._retrieve_multi(url, DocumentAuthor, deref = {"document": "id"})


    def documents_authored_by_person(self, person : Person) -> Iterator[DocumentAuthor]:
        url = DocumentAuthorURI("/api/v1/doc/documentauthor/")
        url.params["person"] = person.id
        return self._retrieve_multi(url, DocumentAuthor, deref = {"document": "id"})


    def documents_authored_by_email(self, email : Email) -> Iterator[DocumentAuthor]:
        url = DocumentAuthorURI("/api/v1/doc/documentauthor/")
        url.params["email"] = email.address
        return self._retrieve_multi(url, DocumentAuthor, deref = {"email" : "address"})


    # Datatracker API endpoints returning information about related documents:
    #   https://datatracker.ietf.org/api/v1/doc/relateddocument/?source=...      - documents that source draft relates to
    #   https://datatracker.ietf.org/api/v1/doc/relateddocument/?target=...      - documents that relate to target draft
    #   https://datatracker.ietf.org/api/v1/doc/relateddochistory/

    def related_documents(self,
        source               : Optional[Document]         = None,
        target               : Optional[DocumentAlias]    = None,
        relationship_type    : Optional[RelationshipType] = None) -> Iterator[RelatedDocument]:

        url = RelatedDocumentURI("/api/v1/doc/relateddocument/")
        if source is not None:
            url.params["source"] = source.id
        if target is not None:
            url.params["target"] = target.id
        if relationship_type is not None:
            url.params["relationship"] = relationship_type.slug
        return self._retrieve_multi(url, RelatedDocument, deref = {"source": "id", "target": "id", "relationship": "slug"})


    def relationship_type(self, relationship_type_uri: RelationshipTypeURI) -> Optional[RelationshipType]:
        """
        Retrieve a relationship type

        Parameters:
            relationship_type_uri -- The relationship type uri,
            as found in the resource_uri of a relationship type.

        Returns:
            A RelationshipType object
        """
        return self._retrieve(relationship_type_uri, RelationshipType)


    def relationship_types(self) -> Iterator[RelationshipType]:
        """
        A generator returning the possible relationship types

        Parameters:
           None

        Returns:
            An iterator of RelationshipType objects
        """
        url = RelationshipTypeURI("/api/v1/name/docrelationshipname/")
        return self._retrieve_multi(url, RelationshipType)


    # Datatracker API endpoints returning information about document history:
    #   https://datatracker.ietf.org/api/v1/doc/dochistory/
    #   https://datatracker.ietf.org/api/v1/doc/dochistoryauthor/

    # FIXME: implement document history methods


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about ballots and document approval:
    # * https://datatracker.ietf.org/api/v1/name/ballotpositionname/
    #   https://datatracker.ietf.org/api/v1/doc/ballotpositiondocevent/
    # * https://datatracker.ietf.org/api/v1/doc/ballottype/
    # * https://datatracker.ietf.org/api/v1/doc/ballotdocevent/

    def ballot_position_name(self, ballot_position_name_uri : BallotPositionNameURI) -> Optional[BallotPositionName]:
        return self._retrieve(ballot_position_name_uri, BallotPositionName)


    def ballot_position_names(self) -> Iterator[BallotPositionName]:
        """
        A generator returning information about ballot position names. These describe
        the names of the responses that a person can give to a ballot (e.g., "Discuss",
        "Abstain", "No Objection", ...).

        Returns:
           A sequence of BallotPositionName objects
        """
        url = BallotPositionNameURI("/api/v1/name/ballotpositionname/")
        return self._retrieve_multi(url, BallotPositionName)


    def ballot_type(self, ballot_type_uri : BallotTypeURI) -> Optional[BallotType]:
        return self._retrieve(ballot_type_uri, BallotType)


    def ballot_types(self, doc_type : Optional[DocumentType]) -> Iterator[BallotType]:
        """
        A generator returning information about ballot types.

        Parameters:
            doc_type     -- Only return ballot types relating to this document type

        Returns:
           A sequence of BallotType objects
        """
        url = BallotTypeURI("/api/v1/doc/ballottype/")
        if doc_type is not None:
            url.params["doc_type"] = doc_type.slug
        return self._retrieve_multi(url, BallotType, deref = {"doc_type": "slug"})



    def ballot_document_event(self, ballot_event_uri : BallotDocumentEventURI) -> Optional[BallotDocumentEvent]:
        return self._retrieve(ballot_event_uri, BallotDocumentEvent)


    def ballot_document_events(self,
                        since       : str = "1970-01-01T00:00:00",
                        until       : str = "2038-01-19T03:14:07",
                        ballot_type : Optional[BallotType]    = None,
                        event_type  : Optional[str]           = None,
                        by          : Optional[Person]        = None,
                        doc         : Optional[Document]      = None) -> Iterator[BallotDocumentEvent]:
        """
        A generator returning information about ballot document events.

        Parameters:
            since        -- Only return ballot document events with timestamp after this
            until        -- Only return ballot document events with timestamp after this
            ballot_type  -- Only return ballot document events of this ballot type
            event_type   -- Only return ballot document events with this type
            by           -- Only return ballot document events by this person
            doc          -- Only return ballot document events that relate to this document

        Returns:
           A sequence of BallotDocumentEvent objects
        """
        url = BallotDocumentEventURI("/api/v1/doc/ballotdocevent/")
        url.params["time__gt"] = since
        url.params["time__lt"] = until
        if ballot_type is not None:
            url.params["ballot_type"] = ballot_type.id
        if by is not None:
            url.params["by"] = by.id
        if doc is not None:
            url.params["doc"] = doc.id
        url.params["type"] = event_type
        return self._retrieve_multi(url, BallotDocumentEvent, deref = {"ballot_type": "id", "by": "id", "doc": "id"})


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about document submissions:
    # * https://datatracker.ietf.org/api/v1/submit/submission/
    # * https://datatracker.ietf.org/api/v1/submit/submissionevent/
    #   https://datatracker.ietf.org/api/v1/submit/submissioncheck/
    #   https://datatracker.ietf.org/api/v1/submit/preapproval/

    def submission(self, submission_uri: SubmissionURI) -> Optional[Submission]:
        return self._retrieve(submission_uri, Submission)


    def submissions(self,
            since           : str = "1970-01-01T00:00:00",
            until           : str = "2038-01-19T03:14:07") -> Iterator[Submission]:
        url = SubmissionURI("/api/v1/submit/submission/")
        url.params["time__gt"] = since
        url.params["time__lt"] = until
        return self._retrieve_multi(url, Submission)


    def submission_event(self, event_uri: SubmissionEventURI) -> Optional[SubmissionEvent]:
        return self._retrieve(event_uri, SubmissionEvent)


    def submission_events(self,
                        since      : str = "1970-01-01T00:00:00",
                        until      : str = "2038-01-19T03:14:07",
                        by         : Optional[Person]     = None,
                        submission : Optional[Submission] = None) -> Iterator[SubmissionEvent]:
        """
        A generator returning information about submission events.

        Parameters:
            since      -- Only return submission events with timestamp after this
            until      -- Only return submission events with timestamp after this
            by         -- Only return submission events by this person
            submission -- Only return submission events about this submission

        Returns:
           A sequence of SubmissionEvent objects
        """
        url = SubmissionEventURI("/api/v1/submit/submissionevent/")
        url.params["time__gt"] = since
        url.params["time__lt"] = until
        if by is not None:
            url.params["by"] = by.id
        if submission is not None:
            url.params["submission"] = submission.id
        return self._retrieve_multi(url, SubmissionEvent, deref = {"by": "id", "submission": "id"})

    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning miscellaneous information about documents:
    #   https://datatracker.ietf.org/api/v1/doc/docreminder/
    #   https://datatracker.ietf.org/api/v1/doc/documenturl/
    #   https://datatracker.ietf.org/api/v1/doc/deletedevent/

    # FIXME: implement these


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about RFC publication streams:
    # * https://datatracker.ietf.org/api/v1/name/streamname/

    def stream(self, stream_uri: StreamURI) -> Optional[Stream]:
        return self._retrieve(stream_uri, Stream)


    def streams(self) -> Iterator[Stream]:
        return self._retrieve_multi(StreamURI("/api/v1/name/streamname/"), Stream)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about working groups:
    # * https://datatracker.ietf.org/api/v1/group/group/                               - list of groups
    # * https://datatracker.ietf.org/api/v1/group/group/2161/                          - info about group 2161
    # * https://datatracker.ietf.org/api/v1/group/grouphistory/?group=2161             - history
    # * https://datatracker.ietf.org/api/v1/group/groupurl/?group=2161                 - URLs
    # * https://datatracker.ietf.org/api/v1/group/groupevent/?group=2161               - events
    # * https://datatracker.ietf.org/api/v1/group/groupmilestone/?group=2161           - Current milestones
    # * https://datatracker.ietf.org/api/v1/group/groupmilestonehistory/?group=2161    - Previous milestones
    # * https://datatracker.ietf.org/api/v1/group/milestonegroupevent/?group=2161      - changed milestones
    # * https://datatracker.ietf.org/api/v1/group/role/?group=2161                     - The current WG chairs and ADs of a group
    # * https://datatracker.ietf.org/api/v1/group/role/?person=20209                   - Groups a person is currently involved with
    # * https://datatracker.ietf.org/api/v1/group/role/?email=csp@csperkins.org        - Groups a person is currently involved with
    # * https://datatracker.ietf.org/api/v1/group/rolehistory/?group=2161              - The previous WG chairs and ADs of a group
    # * https://datatracker.ietf.org/api/v1/group/rolehistory/?person=20209            - Groups person was previously involved with
    # * https://datatracker.ietf.org/api/v1/group/rolehistory/?email=csp@csperkins.org - Groups person was previously involved with
    # * https://datatracker.ietf.org/api/v1/group/changestategroupevent/?group=2161    - Group state changes
    #   https://datatracker.ietf.org/api/v1/group/groupstatetransitions                - ???
    # * https://datatracker.ietf.org/api/v1/name/groupstatename/
    # * https://datatracker.ietf.org/api/v1/name/grouptypename/

    def group(self, group_uri: GroupURI) -> Optional[Group]:
        return self._retrieve(group_uri, Group)


    def group_from_acronym(self, acronym: str) -> Optional[Group]:
        url = GroupURI("/api/v1/group/group/")
        url.params["acronym"] = acronym
        groups = list(self._retrieve_multi(url, Group))
        if len(groups) == 0:
            return None
        elif len(groups) == 1:
            return groups[0]
        else:
            raise RuntimeError


    def groups(self,
            since         : str                  = "1970-01-01T00:00:00",
            until         : str                  = "2038-01-19T03:14:07",
            name_contains : Optional[str]        = None,
            state         : Optional[GroupState] = None,
            parent        : Optional[Group]      = None) -> Iterator[Group]:
        url = GroupURI("/api/v1/group/group/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        url.params["name__contains"] = name_contains
        if state is not None:
            url.params["state"] = state.slug
        if parent is not None:
            url.params["parent"] = parent.id
        return self._retrieve_multi(url, Group, deref = {"parent": "id", "state": "slug"})


    def group_history(self, group_history_uri: GroupHistoryURI) -> Optional[GroupHistory]:
        return self._retrieve(group_history_uri, GroupHistory)


    def group_histories_from_acronym(self, acronym: str) -> Iterator[GroupHistory]:
        url = GroupHistoryURI("/api/v1/group/grouphistory/")
        url.params["acronym"] = acronym
        return self._retrieve_multi(url, GroupHistory)


    def group_histories(self,
            since         : str                  = "1970-01-01T00:00:00",
            until         : str                  = "2038-01-19T03:14:07",
            state         : Optional[GroupState] = None,
            parent        : Optional[Group]      = None) -> Iterator[GroupHistory]:
        url = GroupHistoryURI("/api/v1/group/grouphistory/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        if state is not None:
            url.params["state"] = state.slug
        if parent is not None:
            url.params["parent"] = parent.id
        return self._retrieve_multi(url, GroupHistory, deref = {"parent": "id", "state": "slug"})


    def group_event(self, group_event_uri : GroupEventURI) -> Optional[GroupEvent]:
        return self._retrieve(group_event_uri, GroupEvent)


    def group_events(self,
            since         : str                  = "1970-01-01T00:00:00",
            until         : str                  = "2038-01-19T03:14:07",
            by            : Optional[Person]     = None,
            group         : Optional[Group]      = None,
            type          : Optional[str]        = None) -> Iterator[GroupEvent]:
        url = GroupEventURI("/api/v1/group/groupevent/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        url.params["type"]           = type
        if by is not None:
            url.params["by"] = by.id
        if group is not None:
            url.params["group"] = group.id
        return self._retrieve_multi(url, GroupEvent, deref = {"by": "id", "group": "id"})

    def group_url(self, group_url_uri: GroupUrlURI) -> Optional[GroupUrl]:
        return self._retrieve(group_url_uri, GroupUrl)


    def group_urls(self, group: Optional[Group] = None) -> Iterator[GroupUrl]:
        url = GroupUrlURI("/api/v1/group/groupurl/")
        if group is not None:
            url.params["group"] = group.id
        return self._retrieve_multi(url, GroupUrl)


    def group_milestone_statename(self, group_milestone_statename_uri: GroupMilestoneStateNameURI) -> Optional[GroupMilestoneStateName]:
        return self._retrieve(group_milestone_statename_uri, GroupMilestoneStateName)


    def group_milestone_statenames(self) -> Iterator[GroupMilestoneStateName]:
        return self._retrieve_multi(GroupMilestoneStateNameURI("/api/v1/name/groupmilestonestatename/"), GroupMilestoneStateName)


    def group_milestone(self, group_milestone_uri : GroupMilestoneURI) -> Optional[GroupMilestone]:
        return self._retrieve(group_milestone_uri, GroupMilestone)


    def group_milestones(self,
            since         : str                               = "1970-01-01T00:00:00",
            until         : str                               = "2038-01-19T03:14:07",
            group         : Optional[Group]                   = None,
            state         : Optional[GroupMilestoneStateName] = None) -> Iterator[GroupMilestone]:
        url = GroupMilestoneURI("/api/v1/group/groupmilestone/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        if group is not None:
            url.params["group"] = group.id
        if state is not None:
            url.params["state"] = state.slug
        return self._retrieve_multi(url, GroupMilestone, deref = {"group": "id", "state": "slug"})


    def role_name(self, role_name_uri: RoleNameURI) -> Optional[RoleName]:
        return self._retrieve(role_name_uri, RoleName)


    def role_names(self) -> Iterator[RoleName]:
        return self._retrieve_multi(RoleNameURI("/api/v1/name/rolename/"), RoleName)


    def group_role(self, group_role_uri : GroupRoleURI) -> Optional[GroupRole]:
        return self._retrieve(group_role_uri, GroupRole)


    def group_roles(self,
            email         : Optional[str]           = None,
            group         : Optional[Group]         = None,
            name          : Optional[RoleName]      = None,
            person        : Optional[Person]        = None) -> Iterator[GroupRole]:
        url = GroupRoleURI("/api/v1/group/role/")
        url.params["email"] = email
        if group is not None:
            url.params["group"] = group.id
        if name is not None:
            url.params["name"] = name.slug
        if person is not None:
            url.params["person"] = person.id
        return self._retrieve_multi(url, GroupRole, deref = {"group": "id", "name": "slug", "person": "id"})


    def group_role_history(self, group_role_history_uri : GroupRoleHistoryURI) -> Optional[GroupRoleHistory]:
        return self._retrieve(group_role_history_uri, GroupRoleHistory)


    def group_role_histories(self,
            email         : Optional[str]           = None,
            group         : Optional[Group]         = None,
            name          : Optional[RoleName]      = None,
            person        : Optional[Person]        = None) -> Iterator[GroupRoleHistory]:
        url = GroupRoleHistoryURI("/api/v1/group/rolehistory/")
        url.params["email"] = email
        if group is not None:
            url.params["group"] = group.id
        if name is not None:
            url.params["name"] = name.slug
        if person is not None:
            url.params["person"] = person.id
        return self._retrieve_multi(url, GroupRoleHistory)


    def group_milestone_history(self, group_milestone_history_uri : GroupMilestoneHistoryURI) -> Optional[GroupMilestoneHistory]:
        return self._retrieve(group_milestone_history_uri, GroupMilestoneHistory)


    def group_milestone_histories(self,
            since         : str                               = "1970-01-01T00:00:00",
            until         : str                               = "2038-01-19T03:14:07",
            group         : Optional[Group]                   = None,
            milestone     : Optional[GroupMilestone]          = None,
            state         : Optional[GroupMilestoneStateName] = None) -> Iterator[GroupMilestoneHistory]:
        url = GroupMilestoneHistoryURI("/api/v1/group/groupmilestonehistory/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        if group is not None:
            url.params["group"] = group.id
        if milestone is not None:
            url.params["milestone"] = milestone.id
        if state is not None:
            url.params["state"] = state.slug
        return self._retrieve_multi(url, GroupMilestoneHistory, deref = {"group": "id", "milestone": "id", "state": "slug"})


    def group_milestone_event(self, group_milestone_event_uri : GroupMilestoneEventURI) -> Optional[GroupMilestoneEvent]:
        return self._retrieve(group_milestone_event_uri, GroupMilestoneEvent)


    def group_milestone_events(self,
            since         : str                        = "1970-01-01T00:00:00",
            until         : str                        = "2038-01-19T03:14:07",
            by            : Optional[Person]           = None,
            group         : Optional[Group]            = None,
            milestone     : Optional[GroupMilestone]   = None,
            type          : Optional[str]              = None) -> Iterator[GroupMilestoneEvent]:
        url = GroupMilestoneEventURI("/api/v1/group/milestonegroupevent/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        url.params["type"]           = type
        if by is not None:
            url.params["by"] = by.id
        if group is not None:
            url.params["group"] = group.id
        if milestone is not None:
            url.params["milestone"] = milestone.id
        return self._retrieve_multi(url, GroupMilestoneEvent, deref = {"by": "id", "group": "id"})


    def group_state_change_event(self, group_state_change_event_uri : GroupStateChangeEventURI) -> Optional[GroupStateChangeEvent]:
        return self._retrieve(group_state_change_event_uri, GroupStateChangeEvent)


    def group_state_change_events(self,
            since         : str                        = "1970-01-01T00:00:00",
            until         : str                        = "2038-01-19T03:14:07",
            by            : Optional[Person]           = None,
            group         : Optional[Group]            = None,
            state         : Optional[GroupState]       = None) -> Iterator[GroupStateChangeEvent]:
        url = GroupStateChangeEventURI("/api/v1/group/changestategroupevent/")
        url.params["time__gt"]       = since
        url.params["time__lt"]       = until
        if by is not None:
            url.params["by"] = by.id
        if group is not None:
            url.params["group"] = group.id
        if state is not None:
            url.params["state"] = state.slug
        return self._retrieve_multi(url, GroupStateChangeEvent, deref = {"by": "id", "group": "id", "state": "slug"})


    def group_state(self, group_state_uri : GroupStateURI) -> Optional[GroupState]:
        """
        Retrieve a GroupState
        Parameters:
           group_state -- The group state, as returned in the 'slug' of a GroupState
                           object. Valid group states include "abandon", "active",
                           "bof", "bof-conc", "conclude", "dormant", "proposed",
                           "replaced", and "unknown".
        Returns:
            A GroupState object
        """
        return self._retrieve(group_state_uri, GroupState)


    def group_states(self) -> Iterator[GroupState]:
        url = GroupStateURI("/api/v1/name/groupstatename/")
        return self._retrieve_multi(url, GroupState)


    def group_type_name(self, group_type_name_uri : GroupTypeNameURI) -> Optional[GroupTypeName]:
        return self._retrieve(group_type_name_uri, GroupTypeName)


    def group_type_names(self) -> Iterator[GroupTypeName]:
        return self._retrieve_multi(GroupTypeNameURI("/api/v1/name/grouptypename/"), GroupTypeName)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about meetings:
    # * https://datatracker.ietf.org/api/v1/meeting/meeting/                        - list of meetings
    # * https://datatracker.ietf.org/api/v1/meeting/meeting/747/                    - information about meeting number 747
    #   https://datatracker.ietf.org/api/v1/meeting/session/                        - list of all sessions in meetings
    #   https://datatracker.ietf.org/api/v1/meeting/session/25886/                  - a session in a meeting
    #   https://datatracker.ietf.org/api/v1/meeting/session/?meeting=747            - sessions in meeting number 747
    #   https://datatracker.ietf.org/api/v1/meeting/session/?meeting=747&group=2161 - sessions in meeting number 747 for group 2161
    # * https://datatracker.ietf.org/api/v1/meeting/schedtimesessassignment/59003/  - a schededuled session within a meeting
    #   https://datatracker.ietf.org/api/v1/meeting/timeslot/9480/                  - a time slot within a meeting (time, duration, location)
    # * https://datatracker.ietf.org/api/v1/meeting/schedule/791/                   - a draft of the meeting agenda
    #   https://datatracker.ietf.org/api/v1/meeting/room/537/                       - a room at a meeting
    #   https://datatracker.ietf.org/api/v1/meeting/floorplan/14/                   - floor plan for a meeting venue
    #   https://datatracker.ietf.org/api/v1/meeting/schedulingevent/                - meetings being scheduled
    #
    #   https://datatracker.ietf.org/meeting/107/agenda.json
    #   https://datatracker.ietf.org/meeting/interim-2020-hrpc-01/agenda.json
    #
    #   https://datatracker.ietf.org/api/v1/name/sessionstatusname/
    #   https://datatracker.ietf.org/api/v1/name/agendatypename/
    #   https://datatracker.ietf.org/api/v1/name/timeslottypename/
    #   https://datatracker.ietf.org/api/v1/name/roomresourcename/
    #   https://datatracker.ietf.org/api/v1/name/countryname/
    #   https://datatracker.ietf.org/api/v1/name/continentname/
    # * https://datatracker.ietf.org/api/v1/name/meetingtypename/
    #   https://datatracker.ietf.org/api/v1/name/importantdatename/

    def meeting_session_assignment(self, assignment_uri : SessionAssignmentURI) -> Optional[SessionAssignment]:
        return self._retrieve(assignment_uri, SessionAssignment)


    def meeting_session_assignments(self, schedule : Schedule) -> Iterator[SessionAssignment]:
        """
        The assignment of sessions to timeslots in a particular version of the
        meeting schedule.
        """
        url = SessionAssignmentURI("/api/v1/meeting/schedtimesessassignment/")
        url.params["schedule"] = schedule.id
        return self._retrieve_multi(url, SessionAssignment, deref = {"schedule": "id"})


    def meeting_schedule(self, schedule_uri : ScheduleURI) -> Optional[Schedule]:
        """
        Information about a particular version of the schedule for a meeting.

        Use `meeting_session_assignments()` to find what sessions are scheduled
        in each timeslot of the meeting in this version of the meeting schedule.
        """
        return self._retrieve(schedule_uri, Schedule)


    def meeting(self, meeting_uri : MeetingURI) -> Optional[Meeting]:
        """
        Information about a meeting.
        """
        return self._retrieve(meeting_uri, Meeting)


    def meetings(self,
            start_date   : str = "1970-01-01",
            end_date     : str = "2038-01-19",
            meeting_type : Optional[MeetingType] = None) -> Iterator[Meeting]:
        """
        Return information about meetings taking place within a particular date range.
        """
        url = MeetingURI("/api/v1/meeting/meeting/")
        url.params["date__gte"] = start_date
        url.params["date__lte"] = end_date
        if meeting_type is not None:
            url.params["type"] = meeting_type.slug
        return self._retrieve_multi(url, Meeting, deref = {"type": "slug"})



    def meeting_type(self, meeting_type: str) -> Optional[MeetingType]:
        """
        Retrieve a MeetingType

        Parameters:
           meeting_type -- The meeting type, as returned in the 'slug' of a MeetingType
                           object. Valid meeting types include "ietf" and "interim".

        Returns:
            A MeetingType object
        """
        url = MeetingTypeURI("/api/v1/name/meetingtypename/" + meeting_type + "/")
        return self._retrieve(url, MeetingType)


    def meeting_types(self) -> Iterator[MeetingType]:
        """
        A generator returning the possible meeting types

        Parameters:
           None

        Returns:
            An iterator of MeetingType objects
        """
        return self._retrieve_multi(MeetingTypeURI("/api/v1/name/meetingtypename/"), MeetingType)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about IPR disclosures:
    #
    #   https://datatracker.ietf.org/api/v1/ipr/iprdocrel/
    #   https://datatracker.ietf.org/api/v1/ipr/iprdisclosurebase/
    #
    #   https://datatracker.ietf.org/api/v1/ipr/genericiprdisclosure/
    #   https://datatracker.ietf.org/api/v1/ipr/holderiprdisclosure/
    #   https://datatracker.ietf.org/api/v1/ipr/thirdpartyiprdisclosure
    #
    #   https://datatracker.ietf.org/api/v1/ipr/nondocspecificiprdisclosure/
    #   https://datatracker.ietf.org/api/v1/ipr/relatedipr/
    #
    #   https://datatracker.ietf.org/api/v1/ipr/iprevent/
    #   https://datatracker.ietf.org/api/v1/ipr/legacymigrationiprevent/
    #
    #   https://datatracker.ietf.org/api/v1/name/iprdisclosurestatename/
    #   https://datatracker.ietf.org/api/v1/name/ipreventtypename/
    #   https://datatracker.ietf.org/api/v1/name/iprlicensetypename/

    # FIXME: implement these


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about liaison statements:
    #
    #   https://datatracker.ietf.org/api/v1/liaisons/liaisonstatement/
    #   https://datatracker.ietf.org/api/v1/liaisons/liaisonstatementevent/
    #   https://datatracker.ietf.org/api/v1/liaisons/liaisonstatementgroupcontacts/
    #   https://datatracker.ietf.org/api/v1/liaisons/relatedliaisonstatement/
    #   https://datatracker.ietf.org/api/v1/liaisons/liaisonstatementattachment/
    #
    #   https://datatracker.ietf.org/api/v1/name/liaisonstatementeventtypename/
    #   https://datatracker.ietf.org/api/v1/name/liaisonstatementpurposename/
    #   https://datatracker.ietf.org/api/v1/name/liaisonstatementstate/
    #   https://datatracker.ietf.org/api/v1/name/liaisonstatementtagname/

    # FIXME: implement these


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about reviews:
    #
    #   https://datatracker.ietf.org/api/v1/review/reviewassignment/
    #   https://datatracker.ietf.org/api/v1/review/reviewrequest/
    #   https://datatracker.ietf.org/api/v1/review/reviewwish/
    #   https://datatracker.ietf.org/api/v1/review/reviewteamsettings/
    #   https://datatracker.ietf.org/api/v1/review/nextreviewerinteam/
    #   https://datatracker.ietf.org/api/v1/review/historicalunavailableperiod/
    #   https://datatracker.ietf.org/api/v1/review/historicalreviewrequest/
    #   https://datatracker.ietf.org/api/v1/review/reviewersettings/
    #   https://datatracker.ietf.org/api/v1/review/unavailableperiod/
    #   https://datatracker.ietf.org/api/v1/review/historicalreviewersettings/
    #   https://datatracker.ietf.org/api/v1/review/historicalreviewassignment/
    #   https://datatracker.ietf.org/api/v1/review/reviewsecretarysettings/

    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about mailing lists:
    #
    #   https://datatracker.ietf.org/api/v1/mailinglists/list/
    #   https://datatracker.ietf.org/api/v1/mailinglists/subscribed/

    def mailing_list(self, mailing_list_uri: MailingListURI) -> Optional[MailingList]:
        return self._retrieve(mailing_list_uri, MailingList)


    def mailing_lists(self) -> Iterator[MailingList]:
        url = MailingListURI("/api/v1/mailinglists/list/")
        return self._retrieve_multi(url, MailingList)


    def mailing_list_subscriptions(self, email_addr : Optional[str]) -> Iterator[MailingListSubscriptions]:
        url = MailingListSubscriptionsURI("/api/v1/mailinglists/subscribed/")
        url.params["email"] = email_addr
        return self._retrieve_multi(url, MailingListSubscriptions)


    # ----------------------------------------------------------------------------------------------------------------------------
    # Datatracker API endpoints returning information about names:
    #
    # FIXME: move these into the appropriate place
    #
    #   https://datatracker.ietf.org/api/v1/name/dbtemplatetypename/
    #   https://datatracker.ietf.org/api/v1/name/docrelationshipname/
    #   https://datatracker.ietf.org/api/v1/name/doctagname/
    #   https://datatracker.ietf.org/api/v1/name/docurltagname/
    #   https://datatracker.ietf.org/api/v1/name/formallanguagename/
    #   https://datatracker.ietf.org/api/v1/name/stdlevelname/
    #   https://datatracker.ietf.org/api/v1/name/reviewrequeststatename/
    #   https://datatracker.ietf.org/api/v1/name/groupmilestonestatename/
    #   https://datatracker.ietf.org/api/v1/name/feedbacktypename/
    #   https://datatracker.ietf.org/api/v1/name/reviewtypename/
    #   https://datatracker.ietf.org/api/v1/name/reviewresultname/
    #   https://datatracker.ietf.org/api/v1/name/topicaudiencename/
    #   https://datatracker.ietf.org/api/v1/name/nomineepositionstatename/
    #   https://datatracker.ietf.org/api/v1/name/constraintname/
    #   https://datatracker.ietf.org/api/v1/name/docremindertypename/
    #   https://datatracker.ietf.org/api/v1/name/intendedstdlevelname/
    #   https://datatracker.ietf.org/api/v1/name/draftsubmissionstatename/
    #   https://datatracker.ietf.org/api/v1/name/rolename/

# =================================================================================================================================
# vim: set tw=0 ai:
