"""
Authority registry for Indian legal sources.

Used by the web-search pipeline to decide how much authority a retrieved page
carries.  Official statutory and judicial publishers are ranked above
commentary sites; aggregator/copy sites (Indian Kanoon and friends) are kept
in a clearly separate "secondary" bucket and are never presented as primary
authority.

No network access happens here - this module is pure data + matching logic so
it is cheap to unit test.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Tier vocabulary used across the API surface.
TIER_PRIMARY = "primary"        # Statute / judgment publisher (India Code, SCI, HC)
TIER_OFFICIAL = "official"      # Regulator / government body
TIER_SECONDARY = "secondary"    # Commentary, aggregators, republishers
TIER_OTHER = "other"            # Unclassified web page

KIND_STATUTE = "statute"
KIND_JUDGMENT = "judgment"
KIND_COURT = "court"
KIND_REGULATOR = "regulator"
KIND_FILING = "filing"
KIND_COMMENTARY = "commentary"
KIND_OTHER = "other"


@dataclass
class SourceProfile:
    """How authoritative a host is, and what jurisdiction it speaks for."""

    domain: str
    source_name: str
    tier: str
    authority_score: float
    jurisdiction: str = "India"
    kind: str = KIND_OTHER
    is_official: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "domain": self.domain,
            "source_name": self.source_name,
            "tier": self.tier,
            "authority_score": self.authority_score,
            "jurisdiction": self.jurisdiction,
            "kind": self.kind,
            "is_official": self.is_official,
        }


@dataclass(frozen=True)
class _Rule:
    domain: str
    name: str
    tier: str
    authority: float
    jurisdiction: str = "India"
    kind: str = KIND_OTHER
    notes: str = ""


# --------------------------------------------------------------------------
# Primary publishers: statutes, the Supreme Court and the High Courts.
# --------------------------------------------------------------------------
_PRIMARY_RULES: Tuple[_Rule, ...] = (
    # Central legislation
    _Rule("indiacode.nic.in", "India Code", TIER_PRIMARY, 1.0,
          jurisdiction="India - Union", kind=KIND_STATUTE,
          notes="Official repository of Central Acts, Rules and Schedules."),
    _Rule("legislative.gov.in", "Legislative Department, Parliament of India", TIER_PRIMARY, 0.95,
          jurisdiction="India - Union", kind=KIND_STATUTE),
    _Rule("egazette.nic.in", "Gazette of India", TIER_PRIMARY, 0.95,
          jurisdiction="India - Union", kind=KIND_STATUTE),
    _Rule("egazette.gov.in", "Gazette of India", TIER_PRIMARY, 0.95,
          jurisdiction="India - Union", kind=KIND_STATUTE),
    _Rule("finmin.gov.in", "Ministry of Finance", TIER_PRIMARY, 0.85,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("indiabudget.gov.in", "Union Budget", TIER_PRIMARY, 0.8,
          jurisdiction="India - Union", kind=KIND_STATUTE),

    # Supreme Court of India
    _Rule("sci.gov.in", "Supreme Court of India", TIER_PRIMARY, 1.0,
          jurisdiction="India - Supreme Court", kind=KIND_JUDGMENT,
          notes="Judgments, orders and cause lists of the Supreme Court of India."),
    _Rule("digiscr.sci.gov.in", "Supreme Court of India (Digital Scrapbook)", TIER_PRIMARY, 1.0,
          jurisdiction="India - Supreme Court", kind=KIND_JUDGMENT),
    _Rule("main.sci.gov.in", "Supreme Court of India", TIER_PRIMARY, 1.0,
          jurisdiction="India - Supreme Court", kind=KIND_JUDGMENT),
    _Rule("api.sci.gov.in", "Supreme Court of India Judgments", TIER_PRIMARY, 1.0,
          jurisdiction="India - Supreme Court", kind=KIND_JUDGMENT),
    _Rule("scr.sci.gov.in", "Supreme Court of India - Cause Lists", TIER_PRIMARY, 0.9,
          jurisdiction="India - Supreme Court", kind=KIND_COURT),
    _Rule("scjc.nic.in", "Supreme Court Judgeship Commission", TIER_PRIMARY, 0.8,
          jurisdiction="India - Supreme Court", kind=KIND_REGULATOR),

    # eCourts / National Judicial Data Grid
    _Rule("ecourts.gov.in", "eCourts Services", TIER_PRIMARY, 0.9,
          jurisdiction="India", kind=KIND_COURT,
          notes="Official case status, orders and filing platform."),
    _Rule("njdg.ecourts.gov.in", "National Judicial Data Grid", TIER_PRIMARY, 0.9,
          jurisdiction="India", kind=KIND_COURT),
    _Rule("districts.ecourts.gov.in", "eCourts - District Courts", TIER_PRIMARY, 0.88,
          jurisdiction="India", kind=KIND_COURT),
    _Rule("courtnic.gov.in", "Court NIC", TIER_PRIMARY, 0.8,
          jurisdiction="India", kind=KIND_COURT),

    # Ministry of Justice / Law
    _Rule("lawmin.gov.in", "Ministry of Law and Justice", TIER_PRIMARY, 0.9,
          jurisdiction="India - Union", kind=KIND_STATUTE),
    _Rule("moj.gov.in", "Ministry of Justice and Law", TIER_PRIMARY, 0.88,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("nai.gov.in", "National Archives of India", TIER_PRIMARY, 0.85,
          jurisdiction="India - Union", kind=KIND_STATUTE),

    # Quasi-judicial / statutory regulators
    _Rule("nclc.gov.in", "NCLT / NCLAT", TIER_PRIMARY, 0.92,
          jurisdiction="India - Union", kind=KIND_COURT),
    _Rule("cci.gov.in", "Competition Commission of India", TIER_PRIMARY, 0.88,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("ncdrc.nic.in", "National Consumer Disputes Redressal Commission", TIER_PRIMARY, 0.85,
          jurisdiction="India - Union", kind=KIND_COURT),
    _Rule("mca.gov.in", "Ministry of Corporate Affairs", TIER_PRIMARY, 0.85,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("sebi.gov.in", "SEBI", TIER_PRIMARY, 0.85,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("rbi.org.in", "Reserve Bank of India", TIER_OFFICIAL, 0.82,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("irda.gov.in", "IRDAI", TIER_OFFICIAL, 0.8,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("trai.gov.in", "TRAI", TIER_OFFICIAL, 0.8,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("epfo.gov.in", "EPFO", TIER_OFFICIAL, 0.75,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("nta.gov.in", "National Telecom Authority", TIER_OFFICIAL, 0.7,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("pfrda.org.in", "PFRDA", TIER_OFFICIAL, 0.7,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("cg.gov.in", "Controller General of Accounts", TIER_OFFICIAL, 0.75,
          jurisdiction="India - Union", kind=KIND_REGULATOR),
    _Rule("supremecourt.gov.in", "Supreme Court of India", TIER_PRIMARY, 0.95,
          jurisdiction="India - Supreme Court", kind=KIND_JUDGMENT),
)

# --------------------------------------------------------------------------
# Secondary / commentary hosts - never presented as primary authority.
# --------------------------------------------------------------------------
_SECONDARY_RULES: Tuple[_Rule, ...] = (
    _Rule("indiankanoon.org", "Indian Kanoon", TIER_SECONDARY, 0.35,
          jurisdiction="India", kind=KIND_COMMENTARY,
          notes="Free case-law mirror. Useful for text, not an official publisher."),
    _Rule("advocatekhoj.com", "AdvocateKhoj", TIER_SECONDARY, 0.45,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("livelaw.in", "LiveLaw", TIER_SECONDARY, 0.4,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("barandbench.com", "Bar & Bench", TIER_SECONDARY, 0.4,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("scobserver.in", "Supreme Court Observer", TIER_SECONDARY, 0.45,
          jurisdiction="India - Supreme Court", kind=KIND_COMMENTARY),
    _Rule("scconline.com", "Supreme Court Online", TIER_SECONDARY, 0.35,
          jurisdiction="India - Supreme Court", kind=KIND_COMMENTARY),
    _Rule("casemine.com", "CaseMine", TIER_SECONDARY, 0.3,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("legalcrystal.com", "LegalCrystal", TIER_SECONDARY, 0.3,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("latestlaws.com", "LatestLaws", TIER_SECONDARY, 0.3,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("lawyerservices.in", "LawyerServices", TIER_SECONDARY, 0.3,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("wikipedia.org", "Wikipedia", TIER_SECONDARY, 0.2,
          jurisdiction="India", kind=KIND_COMMENTARY),
    _Rule("taxmann.com", "Taxmann", TIER_SECONDARY, 0.3,
          jurisdiction="India", kind=KIND_COMMENTARY),
)

# Hosts that are never legal authority, whatever they claim to be.
_BLOCKED_DOMAINS = {
    "medium.com", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "reddit.com", "quora.com", "pinterest.com", "tiktok.com", "instagram.com",
    "youtube.com", "blogspot.com", "wordpress.com", "blogger.com",
    "scribd.com", "slideshare.net", "issuu.com", "researchgate.net",
    "amazon.in", "amazon.com", "flipkart.com", "ebay.in",
}

# eCourts serves every High Court from a `hc-<state>-<bench>.ecourts.gov.in`
# host.  The two-letter code is used to label the jurisdiction.
_ECOURTS_STATE_CODES: Dict[str, str] = {
    "ap": "Andhra Pradesh", "ar": "Arunachal Pradesh", "as": "Assam",
    "br": "Bihar", "cg": "Chhattisgarh", "dh": "Dadra and Nagar Haveli and Daman and Diu",
    "dl": "Delhi", "ga": "Goa", "gj": "Gujarat", "hp": "Himachal Pradesh",
    "hr": "Haryana", "jh": "Jharkhand", "jk": "Jammu and Kashmir", "ka": "Karnataka",
    "kl": "Kerala", "la": "Ladakh", "ld": "Lakshadweep", "ml": "Meghalaya",
    "mn": "Manipur", "mp": "Madhya Pradesh", "mz": "Mizoram", "nl": "Nagaland",
    "od": "Odisha", "pb": "Punjab", "py": "Puducherry", "rj": "Rajasthan",
    "sk": "Sikkim", "tg": "Telangana", "tn": "Tamil Nadu", "tr": "Tripura",
    "ts": "Telangana", "uk": "Uttarakhand", "up": "Uttar Pradesh",
    "wb": "West Bengal", "mh": "Maharashtra",
}

# Directories whose host token identifies the High Court.
_HIGH_COURT_TOKENS: Dict[str, str] = {
    "bom": "Bombay High Court (Maharashtra & Goa)",
    "mumbai": "Bombay High Court (Maharashtra & Goa)",
    "delhi": "Delhi High Court",
    "cal": "Calcutta High Court (West Bengal & Sikkim)",
    "calcutta": "Calcutta High Court (West Bengal & Sikkim)",
    "kolkata": "Calcutta High Court (West Bengal & Sikkim)",
    "mad": "Madras High Court (Tamil Nadu & Puducherry)",
    "madras": "Madras High Court (Tamil Nadu & Puducherry)",
    "kar": "Karnataka High Court",
    "karnataka": "Karnataka High Court",
    "karunadu": "Karnataka High Court",
    "pat": "Patna High Court (Bihar & Jharkhand)",
    "all": "Allahabad High Court (Uttar Pradesh)",
    "allahabad": "Allahabad High Court (Uttar Pradesh)",
    "gau": "Gauhati High Court (Assam, Arunachal Pradesh & Nagaland)",
    "guwahati": "Gauhati High Court (Assam, Arunachal Pradesh & Nagaland)",
    "aja": "Gauhati High Court (Assam, Arunachal Pradesh & Nagaland)",
    "cgh": "Chhattisgarh High Court",
    "mpr": "Madhya Pradesh High Court",
    "ojh": "Orissa High Court (Odisha)",
    "odisha": "Orissa High Court (Odisha)",
    "uk": "Uttarakhand High Court",
    "hp": "Himachal Pradesh High Court",
    "pnb": "Punjab & Haryana High Court",
    "chd": "Punjab & Haryana High Court (Chandigarh)",
    "j&k": "Jammu & Kashmir High Court",
    "sk": "Sikkim High Court",
    "ml": "Meghalaya High Court",
    "mz": "Mizoram High Court",
    "trip": "Tripura High Court",
    "man": "Manipur High Court",
    "nag": "Nagaland High Court",
    "arunachal": "Arunachal Pradesh High Court",
    "goa": "Goa High Court",
    "rajasthan": "Rajasthan High Court",
    "haryana": "Punjab & Haryana High Court",
    "punjab": "Punjab & Haryana High Court",
    "tamilnadu": "Madras High Court (Tamil Nadu & Puducherry)",
    "andhra": "Andhra Pradesh High Court",
    "telangana": "Telangana High Court",
    "kerala": "Kerala High Court",
    "gujarat": "Gujarat High Court",
    "uttarakhand": "Uttarakhand High Court",
    "himachal": "Himachal Pradesh High Court",
    "bhubaneswar": "Orissa High Court (Odisha)",
    "guwahati": "Gauhati High Court (Assam, Arunachal Pradesh & Nagaland)",
}


def _host_labels(host: str) -> List[str]:
    """Split a hostname into lowercase labels (dots and dashes)."""
    return [lbl for lbl in host.replace("-", ".").split(".") if lbl]


class LegalSourceRegistry:
    """Classifies a hostname into an authority profile."""

    def __init__(
        self,
        primary_rules: Tuple[_Rule, ...] = _PRIMARY_RULES,
        secondary_rules: Tuple[_Rule, ...] = _SECONDARY_RULES,
        blocked_domains=tuple(sorted(_BLOCKED_DOMAINS)),
    ) -> None:
        self._primary = {r.domain: r for r in sorted(primary_rules, key=lambda r: -len(r.domain))}
        self._secondary = {r.domain: r for r in sorted(secondary_rules, key=lambda r: -len(r.domain))}
        self._blocked = set(blocked_domains)

    # -- public API --------------------------------------------------------
    def classify(self, url_or_host: str) -> SourceProfile:
        host = self._extract_host(url_or_host)
        if not host:
            return SourceProfile("", "Unknown", TIER_OTHER, 0.1, jurisdiction="", kind=KIND_OTHER)

        host = host.lower().rstrip(".")

        # eCourts hosts every High Court from a `hc-<state>-<bench>.ecourts.gov.in`
        # host, so this pattern is checked before the generic eCourts rule.
        if host.endswith(".ecourts.gov.in"):
            profile = self._ecourts_high_court_profile(host)
            if profile is not None:
                return profile

        for domain in self._blocked:
            if self._matches(host, domain):
                return SourceProfile(
                    domain=domain, source_name=domain, tier=TIER_OTHER,
                    authority_score=0.0, jurisdiction="", kind=KIND_OTHER,
                    notes="Not a legal authority source.",
                )

        for rule in self._primary.values():
            if self._matches(host, rule.domain):
                return self._from_rule(rule, host)

        for rule in self._secondary.values():
            if self._matches(host, rule.domain):
                return self._from_rule(rule, host)

        profile = self._classify_by_pattern(host)
        if profile is not None:
            return profile

        return SourceProfile(
            domain=host, source_name=host, tier=TIER_OTHER, authority_score=0.2,
            jurisdiction="", kind=KIND_OTHER, notes="Unclassified web source.",
        )

    def is_secondary(self, profile: SourceProfile) -> bool:
        return profile.tier == TIER_SECONDARY

    def official_domains(self) -> List[str]:
        return sorted(self._primary.keys())

    def targeted_site_queries(self, limit: int = 4) -> List[str]:
        """Domain filters used to bias discovery towards official publishers."""
        preferred = [
            "indiacode.nic.in",
            "sci.gov.in",
            "ecourts.gov.in",
            "legislative.gov.in",
        ]
        return preferred[:limit]

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _extract_host(url_or_host: str) -> str:
        value = (url_or_host or "").strip()
        if not value:
            return ""
        if "//" not in value:
            value = "//" + value
        try:
            host = urlparse(value).netloc
        except ValueError:
            return ""
        if "@" in host:
            host = host.split("@", 1)[1]
        if host.startswith("["):  # IPv6 literal
            host = host.split("]", 1)[0].lstrip("[")
        return host.split(":")[0]

    @staticmethod
    def _matches(host: str, domain: str) -> bool:
        return host == domain or host.endswith("." + domain)

    @staticmethod
    def _from_rule(rule: _Rule, host: str) -> SourceProfile:
        return SourceProfile(
            domain=host,
            source_name=rule.name,
            tier=rule.tier,
            authority_score=rule.authority,
            jurisdiction=rule.jurisdiction,
            kind=rule.kind,
            is_official=rule.tier in (TIER_PRIMARY, TIER_OFFICIAL),
            notes=rule.notes,
        )

    def _classify_by_pattern(self, host: str) -> Optional[SourceProfile]:
        labels = _host_labels(host)
        label_set = set(labels)

        # Explicitly named High Court hosts.
        for token, name in _HIGH_COURT_TOKENS.items():
            if token in label_set:
                return SourceProfile(
                    domain=host, source_name=name, tier=TIER_PRIMARY,
                    authority_score=0.9, jurisdiction=f"India - {name}",
                    kind=KIND_COURT, is_official=True,
                    notes="Official High Court website.",
                )

        # Composite host names such as `bomhighcourt.nic.in` or `hcmadras.tn.nic.in`.
        court_name = self._detect_high_court(labels)
        if court_name:
            return SourceProfile(
                domain=host, source_name=court_name, tier=TIER_PRIMARY,
                authority_score=0.9, jurisdiction=f"India - {court_name}",
                kind=KIND_COURT, is_official=True,
                notes="Official High Court website.",
            )

        # Generic government domains that are not individually listed.
        if host.endswith(".gov.in") or host.endswith(".nic.in"):
            return SourceProfile(
                domain=host, source_name=host, tier=TIER_OFFICIAL, authority_score=0.55,
                jurisdiction="India", kind=KIND_OTHER, is_official=True,
                notes="Indian government domain (not a known statute publisher).",
            )

        return None

    @staticmethod
    def _detect_high_court(labels: List[str]) -> Optional[str]:
        """Infer the High Court from composite host labels."""
        for label in labels:
            if "highcourt" in label:
                for token, name in _HIGH_COURT_TOKENS.items():
                    if label.startswith(token) or label.endswith(token) or (
                        len(token) >= 4 and token in label
                    ):
                        return name
                return "High Court of India"
        for label in labels:
            if label.startswith("hc") and len(label) > 2:
                for token, name in _HIGH_COURT_TOKENS.items():
                    if label.startswith(token) or label.endswith(token) or (
                        len(token) >= 4 and token in label
                    ):
                        return name
                return "High Court of India"
        return None

    @staticmethod
    def _ecourts_high_court_profile(host: str) -> Optional[SourceProfile]:
        labels = [lbl for lbl in _host_labels(host) if lbl != "www"]
        if not labels or labels[0] != "hc":
            return None
        state = ""
        for lbl in labels[1:3]:
            if lbl in _ECOURTS_STATE_CODES:
                state = _ECOURTS_STATE_CODES[lbl]
                break
        jurisdiction = f"India - {state} High Court" if state else "India - High Court"
        return SourceProfile(
            domain=host, source_name=f"{state or 'Indian'} High Court (eCourts)",
            tier=TIER_PRIMARY, authority_score=0.88, jurisdiction=jurisdiction,
            kind=KIND_COURT, is_official=True,
            notes="Official eCourts hosted High Court website.",
        )


legal_source_registry = LegalSourceRegistry()
