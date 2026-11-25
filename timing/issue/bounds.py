from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from timing.issue.intervals import TimeInterval
from timing.source.observations import Observation


@dataclass(frozen=True)
class ConstraintGraph:
    vertices: tuple[str, ...]
    edges: tuple[Observation, ...]


def build_constraint_graph(
    observations: Iterable[Observation], anchors: tuple[str, str]
) -> ConstraintGraph:
    edges = tuple(observations)
    vertices = set(anchors)
    for edge in edges:
        vertices.update((edge.start, edge.end))
    return ConstraintGraph(tuple(sorted(vertices)), edges)


def tightest_upper_bound(graph: ConstraintGraph, start: str, end: str) -> Fraction | None:
    '''Return the shortest directed bound in an already qualified graph.'''
    distances = {start: Fraction(0)}
    for _ in range(len(graph.vertices) - 1):
        changed = False
        for edge in graph.edges:
            if edge.start not in distances:
                continue
            proposed = distances[edge.start] + edge.upper_ms
            current = distances.get(edge.end)
            if current is None or proposed < current:
                distances[edge.end] = proposed
                changed = True
        if not changed:
            break
    return distances.get(end)


def project_anchor_pair(graph: ConstraintGraph, anchors: tuple[str, str]) -> TimeInterval:
    '''Project a feasible graph to the difference from the first anchor to the second.'''
    start, end = anchors
    upper = tightest_upper_bound(graph, start, end)
    reverse_bound = tightest_upper_bound(graph, end, start)
    lower = None if reverse_bound is None else -reverse_bound
    return TimeInterval(lower, upper)
