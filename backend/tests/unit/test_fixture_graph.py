from maestro_app.domain.enums import FixturePhase, FixtureScope
from maestro_app.domain.fixture_graph import FixtureDependencyResolver
from maestro_app.domain.models import FixtureDefinition, SourceStep


def _fixture(fixture_id: str, order: int, dependencies=()) -> FixtureDefinition:
    return FixtureDefinition(
        fixture_id=fixture_id,
        title=fixture_id,
        phase=FixturePhase.SETUP,
        scope=FixtureScope.FUNCTION,
        dependency_ids=list(dependencies),
        order=order,
        steps=[SourceStep(ordinal=1, text="点击【确认】")],
        expected_results=[SourceStep(ordinal=1, text="页面显示【完成】")],
        source_row=6,
    )


def test_topological_sort_expands_indirect_dependencies_once() -> None:
    resolver = FixtureDependencyResolver(
        [
            _fixture("FX-A", 30, ["FX-B", "FX-C"]),
            _fixture("FX-B", 20, ["FX-C"]),
            _fixture("FX-C", 10),
        ]
    )

    assert resolver.resolve(["FX-A", "FX-B"]) == ["FX-C", "FX-B", "FX-A"]


def test_same_level_uses_order_then_id() -> None:
    resolver = FixtureDependencyResolver(
        [_fixture("FX-B", 10), _fixture("FX-A", 10), _fixture("FX-C", 5)]
    )

    assert resolver.resolve(["FX-A", "FX-B", "FX-C"]) == [
        "FX-C",
        "FX-A",
        "FX-B",
    ]


def test_wider_scope_cannot_depend_on_shorter_scope():
    parent = _fixture("S", 20, ["F"]).model_copy(update={"scope": FixtureScope.SESSION})
    assert "FIXTURE_DEPENDENCY_SCOPE_MISMATCH" in {issue.code for issue in FixtureDependencyResolver([parent, _fixture("F", 10)]).validate()}
    child = _fixture("F", 20, ["S"])
    parent = parent.model_copy(update={"dependency_ids": []})
    assert not FixtureDependencyResolver([parent, child]).validate()
