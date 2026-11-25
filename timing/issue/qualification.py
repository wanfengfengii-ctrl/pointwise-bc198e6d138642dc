from fractions import Fraction

from timing.issue.bounds import ConstraintGraph


def is_feasible(graph: ConstraintGraph) -> bool:
    # Zero initial distances represent a common source to every component.
    distances = dict.fromkeys(graph.vertices, Fraction(0))
    for _ in graph.vertices:
        changed = False
        for edge in graph.edges:
            proposed = distances[edge.start] + edge.upper_ms
            if proposed < distances[edge.end]:
                distances[edge.end] = proposed
                changed = True
        if not changed:
            return True
    return not graph.vertices
