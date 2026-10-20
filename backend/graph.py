from langgraph.graph import END, START, StateGraph

from backend.agents.analyst import analyst_node
from backend.agents.researcher import researcher_node
from backend.agents.verifier import verifier_node
from backend.agents.writer import writer_node
from backend.state import FinSageState


def route_after_verifier(state: FinSageState) -> str:
    """If the Verifier left feedback, the draft goes back to the Writer."""
    return "writer" if state.get("feedback") else "end"


def build_graph():
    graph = StateGraph(FinSageState)
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_node("verifier", verifier_node)

    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "verifier")
    graph.add_conditional_edges("verifier", route_after_verifier, {"writer": "writer", "end": END})
    return graph.compile()