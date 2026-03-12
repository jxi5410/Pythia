"""
BACE Ontology Extractor — Rich entity-relationship graph from spike context.

MiroFish builds an ontology from seed documents for forward simulation.
We reverse it: build an ontology from a spike event to map the causal landscape.

Produces typed entities (Person, Organization, Policy, DataRelease, Market,
GeopoliticalEvent) and typed relationships (announced, responded_to, preceded,
correlates_with, regulates) that become the search space for causal agents.

Replaces causal_v2.extract_entities_llm() which only produces 3-5 flat keywords.
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Entity and Relationship types
# ----------------------------------------------------------------

ENTITY_TYPES = [
    "Person",           # Powell, Trump, Lagarde, Zelenskyy
    "Organization",     # Fed, PBOC, SEC, BlackRock, USTR
    "Policy",           # Executive order, rate decision, regulation
    "DataRelease",      # CPI, NFP, GDP, PMI, earnings
    "Market",           # BTC, SPY, TLT, specific Polymarket contracts
    "GeopoliticalEvent",# Ceasefire, sanctions, military exercises
    "Narrative",        # "Risk-on rotation", "flight to safety"
    "FinancialInstrument",  # ETF, futures, options specific
    "TechEvent",        # Product launch, acquisition, regulatory action
]

RELATIONSHIP_TYPES = [
    "announced",        # Person/Org → Policy/DataRelease
    "responded_to",     # Org/Person → Policy/Event (retaliatory)
    "preceded",         # Event → Event (temporal)
    "correlates_with",  # Market → Market
    "regulates",        # Org → Market/FinancialInstrument
    "influences",       # Person → Policy
    "triggers",         # Event → Market move
    "contradicts",      # Event → Event (opposing signals)
    "amplifies",        # Event → Event (reinforcing)
]


@dataclass
class Entity:
    id: str
    name: str
    entity_type: str
    description: str = ""
    search_terms: List[str] = field(default_factory=list)
    relevance_score: float = 0.0  # 0-1 estimated relevance to spike


@dataclass
class Relationship:
    source_id: str
    target_id: str
    relationship_type: str
    description: str = ""
    temporal_order: Optional[str] = None  # 'before', 'after', 'concurrent'
    strength: float = 0.5


@dataclass
class CausalOntology:
    """Full entity-relationship graph for a spike's causal landscape."""
    spike_market_id: str
    spike_market_title: str
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)  # derived search terms

    def to_dict(self) -> Dict:
        return {
            "spike_market_id": self.spike_market_id,
            "spike_market_title": self.spike_market_title,
            "entities": [asdict(e) for e in self.entities],
            "relationships": [asdict(r) for r in self.relationships],
            "search_queries": self.search_queries,
        }

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        return [e for e in self.entities if e.entity_type == entity_type]

    def get_all_search_terms(self) -> List[str]:
        """Collect all unique search terms from entities + derived queries."""
        terms = set(self.search_queries)
        for e in self.entities:
            terms.update(e.search_terms)
        return list(terms)


# ----------------------------------------------------------------
# Ontology extraction prompt
# ----------------------------------------------------------------

ONTOLOGY_PROMPT = """You are a causal analyst for prediction markets. A price spike has been detected:

Market: {market_title}
Category: {category}
Direction: {direction} {magnitude:.1%}
Timestamp: {timestamp}
Concurrent spikes: {concurrent_spikes}

Your task: Build a comprehensive entity-relationship graph of everything that COULD have caused this spike.

Think broadly. Include:
- Direct triggers (policy announcements, data releases, breaking news)
- Indirect causes (supply chain disruptions, diplomatic signals, leaked information)
- Background conditions (market regime, sentiment shifts, positioning)
- Key actors (officials, institutions, market participants)
- Related markets and instruments

Return ONLY valid JSON with this exact structure:
{{
  "entities": [
    {{
      "id": "unique-id",
      "name": "Entity Name",
      "entity_type": "Person|Organization|Policy|DataRelease|Market|GeopoliticalEvent|Narrative|FinancialInstrument|TechEvent",
      "description": "Why this entity might be relevant to the spike",
      "search_terms": ["term1", "term2"],
      "relevance_score": 0.8
    }}
  ],
  "relationships": [
    {{
      "source_id": "entity-id-1",
      "target_id": "entity-id-2",
      "relationship_type": "announced|responded_to|preceded|correlates_with|regulates|influences|triggers|contradicts|amplifies",
      "description": "How these entities are connected",
      "strength": 0.7
    }}
  ],
  "search_queries": [
    "specific search query to find evidence for this entity or relationship"
  ]
}}

Generate at least 12 entities and 15 relationships. Include long-tail possibilities.
Search queries should be specific enough to find relevant news within a 6-hour window.
"""


def extract_causal_ontology(
    spike_context: Dict,
    llm_call=None,
) -> CausalOntology:
    """
    Extract a rich causal ontology from spike context.

    Args:
        spike_context: Context dict from build_spike_context()
        llm_call: function(prompt) -> str. If None, uses fallback extraction.

    Returns:
        CausalOntology with typed entities, relationships, and search queries.
    """
    market_title = spike_context.get("market_title", "Unknown market")
    category = spike_context.get("category", "general")
    spike = spike_context.get("spike", {})
    correlated = spike_context.get("correlated_spikes", [])

    concurrent_desc = "None" if not correlated else ", ".join(
        f"{c['market_title'][:40]} ({c['direction']} {c['magnitude']:.1%})"
        for c in correlated[:5]
    )

    prompt = ONTOLOGY_PROMPT.format(
        market_title=market_title,
        category=category,
        direction=spike.get("direction", "up"),
        magnitude=float(spike.get("magnitude", 0)),
        timestamp=spike.get("timestamp", ""),
        concurrent_spikes=concurrent_desc,
    )

    ontology = CausalOntology(
        spike_market_id=spike.get("market_id", ""),
        spike_market_title=market_title,
    )

    if llm_call:
        try:
            response = llm_call(prompt)
            parsed = _parse_ontology_response(response)
            if parsed:
                ontology.entities = [
                    Entity(**{k: v for k, v in e.items() if k in Entity.__dataclass_fields__})
                    for e in parsed.get("entities", [])
                ]
                ontology.relationships = [
                    Relationship(**{k: v for k, v in r.items() if k in Relationship.__dataclass_fields__})
                    for r in parsed.get("relationships", [])
                ]
                ontology.search_queries = parsed.get("search_queries", [])

                logger.info(
                    "Ontology extracted: %d entities, %d relationships, %d queries",
                    len(ontology.entities), len(ontology.relationships), len(ontology.search_queries),
                )
                return ontology
        except Exception as e:
            logger.warning("LLM ontology extraction failed: %s", e)

    # Fallback: keyword-based extraction (matches depth-1 behavior)
    ontology = _fallback_extraction(spike_context)
    return ontology


def _parse_ontology_response(response: str) -> Optional[Dict]:
    """Parse LLM response into ontology dict, handling common formatting issues."""
    if not response:
        return None

    # Strip markdown code fences
    text = response.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in response
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    logger.warning("Failed to parse ontology response")
    return None


# ----------------------------------------------------------------
# Category-specific entity templates (fallback when no LLM)
# ----------------------------------------------------------------

CATEGORY_TEMPLATES: Dict[str, List[Dict]] = {
    "fed_rate": [
        {"id": "fed", "name": "Federal Reserve", "entity_type": "Organization", "search_terms": ["Federal Reserve", "FOMC", "Fed"]},
        {"id": "powell", "name": "Jerome Powell", "entity_type": "Person", "search_terms": ["Powell speech", "Powell statement"]},
        {"id": "fomc-minutes", "name": "FOMC Minutes", "entity_type": "DataRelease", "search_terms": ["FOMC minutes", "Fed minutes"]},
        {"id": "pce", "name": "PCE Inflation", "entity_type": "DataRelease", "search_terms": ["PCE inflation", "core PCE"]},
        {"id": "nfp", "name": "Nonfarm Payrolls", "entity_type": "DataRelease", "search_terms": ["NFP", "jobs report", "nonfarm payrolls"]},
        {"id": "treasury", "name": "Treasury Yields", "entity_type": "Market", "search_terms": ["Treasury yield", "2Y yield", "10Y yield"]},
        {"id": "rate-cut", "name": "Rate Cut Expectations", "entity_type": "Narrative", "search_terms": ["rate cut probability", "CME FedWatch"]},
    ],
    "tariffs": [
        {"id": "ustr", "name": "USTR", "entity_type": "Organization", "search_terms": ["USTR", "trade representative"]},
        {"id": "bis", "name": "Bureau of Industry and Security", "entity_type": "Organization", "search_terms": ["BIS", "export controls", "entity list"]},
        {"id": "moc", "name": "China Ministry of Commerce", "entity_type": "Organization", "search_terms": ["MOFCOM", "China commerce ministry"]},
        {"id": "exec-order", "name": "Executive Order", "entity_type": "Policy", "search_terms": ["executive order tariff", "presidential action"]},
        {"id": "section-301", "name": "Section 301", "entity_type": "Policy", "search_terms": ["Section 301", "trade investigation"]},
        {"id": "retaliation", "name": "Retaliatory Tariffs", "entity_type": "Policy", "search_terms": ["retaliatory tariff", "China retaliation"]},
        {"id": "trade-talks", "name": "Trade Negotiations", "entity_type": "GeopoliticalEvent", "search_terms": ["trade talks", "trade negotiations", "Geneva talks"]},
    ],
    "crypto": [
        {"id": "sec", "name": "SEC", "entity_type": "Organization", "search_terms": ["SEC crypto", "SEC bitcoin"]},
        {"id": "blackrock", "name": "BlackRock", "entity_type": "Organization", "search_terms": ["BlackRock IBIT", "BlackRock ETF"]},
        {"id": "etf-flows", "name": "ETF Flows", "entity_type": "DataRelease", "search_terms": ["bitcoin ETF flows", "IBIT inflows"]},
        {"id": "whale", "name": "Whale Activity", "entity_type": "Narrative", "search_terms": ["whale accumulation", "large bitcoin transfer"]},
        {"id": "tether", "name": "Tether/USDT", "entity_type": "FinancialInstrument", "search_terms": ["Tether attestation", "USDT"]},
        {"id": "halving", "name": "Halving Cycle", "entity_type": "Narrative", "search_terms": ["bitcoin halving", "supply shock"]},
    ],
    "geopolitical": [
        {"id": "un", "name": "UN Security Council", "entity_type": "Organization", "search_terms": ["UNSC resolution", "Security Council"]},
        {"id": "nato", "name": "NATO", "entity_type": "Organization", "search_terms": ["NATO", "alliance"]},
        {"id": "ceasefire", "name": "Ceasefire Negotiations", "entity_type": "GeopoliticalEvent", "search_terms": ["ceasefire talks", "peace negotiations"]},
        {"id": "sanctions", "name": "Sanctions Package", "entity_type": "Policy", "search_terms": ["sanctions", "OFAC"]},
        {"id": "military", "name": "Military Activity", "entity_type": "GeopoliticalEvent", "search_terms": ["military exercises", "troop movements"]},
    ],
}


def _fallback_extraction(spike_context: Dict) -> CausalOntology:
    """Keyword-based ontology extraction when LLM is unavailable."""
    market_title = spike_context.get("market_title", "")
    category = spike_context.get("category", "general")
    spike = spike_context.get("spike", {})

    ontology = CausalOntology(
        spike_market_id=spike.get("market_id", ""),
        spike_market_title=market_title,
    )

    # Use category template if available
    template = CATEGORY_TEMPLATES.get(category, [])
    for t in template:
        ontology.entities.append(Entity(
            id=t["id"],
            name=t["name"],
            entity_type=t["entity_type"],
            search_terms=t.get("search_terms", []),
            relevance_score=0.5,
        ))

    # Extract search queries from entities
    for e in ontology.entities:
        ontology.search_queries.extend(e.search_terms[:2])

    # Add market title keywords as fallback queries
    words = re.findall(r'\b[A-Z][a-z]+\b|\b[A-Z]{2,}\b', market_title)
    if words:
        ontology.search_queries.append(" ".join(words[:4]))

    logger.info(
        "Fallback ontology: %d entities, %d queries (category=%s)",
        len(ontology.entities), len(ontology.search_queries), category,
    )
    return ontology
