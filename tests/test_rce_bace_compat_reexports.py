import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_rce_module_reexports_match_bace_modules():
    import core.rce_agents as rce_agents
    import core.bace_agents as bace_agents
    import core.rce_ontology as rce_ontology
    import core.bace_ontology as bace_ontology
    import core.rce_evidence_provider as rce_evidence_provider
    import core.bace_evidence_provider as bace_evidence_provider

    assert hasattr(rce_agents, "spawn_agents") == hasattr(bace_agents, "spawn_agents")
    assert hasattr(rce_ontology, "extract_causal_ontology") == hasattr(bace_ontology, "extract_causal_ontology")
    assert hasattr(rce_evidence_provider, "gather_all_agent_evidence") == hasattr(bace_evidence_provider, "gather_all_agent_evidence")
