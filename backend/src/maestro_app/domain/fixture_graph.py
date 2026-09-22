from __future__ import annotations

from collections.abc import Iterable

from maestro_app.domain.enums import FixturePhase, Severity
from maestro_app.domain.models import FixtureDefinition, ValidationIssue


class FixtureDependencyResolver:
    def __init__(self, fixtures: Iterable[FixtureDefinition]) -> None:
        self.fixtures = {fixture.fixture_id: fixture for fixture in fixtures}

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for fixture in self.fixtures.values():
            for dependency_id in fixture.dependency_ids:
                dependency = self.fixtures.get(dependency_id)
                if dependency_id == fixture.fixture_id:
                    issues.append(
                        self._issue(
                            "FIXTURE_SELF_DEPENDENCY",
                            fixture,
                            f"夹具 {fixture.fixture_id} 不能依赖自身",
                        )
                    )
                elif dependency is None:
                    issues.append(
                        self._issue(
                            "FIXTURE_DEPENDENCY_MISSING",
                            fixture,
                            f"依赖夹具 {dependency_id} 不存在",
                        )
                    )
                elif fixture.enabled and not dependency.enabled:
                    issues.append(
                        self._issue(
                            "FIXTURE_DEPENDENCY_DISABLED",
                            fixture,
                            f"启用夹具不能依赖停用夹具 {dependency_id}",
                        )
                    )
                elif dependency.phase != fixture.phase:
                    issues.append(
                        self._issue(
                            "FIXTURE_DEPENDENCY_PHASE_MISMATCH",
                            fixture,
                            f"夹具 {fixture.fixture_id} 与依赖 {dependency_id} 的阶段不一致",
                        )
                    )

        cycle = self._find_cycle()
        if cycle:
            first = self.fixtures[cycle[0]]
            issues.append(
                self._issue(
                    "FIXTURE_DEPENDENCY_CYCLE",
                    first,
                    "夹具依赖存在循环：" + " → ".join(cycle),
                )
            )
        return issues

    def resolve(
        self,
        fixture_ids: Iterable[str],
        *,
        phase: FixturePhase | None = None,
    ) -> list[str]:
        closure: set[str] = set()

        def visit(fixture_id: str) -> None:
            fixture = self.fixtures.get(fixture_id)
            if fixture is None or not fixture.enabled:
                return
            if phase is not None and fixture.phase != phase:
                return
            if fixture_id in closure:
                return
            closure.add(fixture_id)
            for dependency_id in fixture.dependency_ids:
                visit(dependency_id)

        for fixture_id in fixture_ids:
            visit(fixture_id)

        indegree = {fixture_id: 0 for fixture_id in closure}
        dependants: dict[str, list[str]] = {fixture_id: [] for fixture_id in closure}
        for fixture_id in closure:
            fixture = self.fixtures[fixture_id]
            for dependency_id in fixture.dependency_ids:
                if dependency_id not in closure:
                    continue
                indegree[fixture_id] += 1
                dependants[dependency_id].append(fixture_id)

        ready = sorted(
            (fixture_id for fixture_id, degree in indegree.items() if degree == 0),
            key=self._sort_key,
        )
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for dependant in sorted(dependants[current], key=self._sort_key):
                indegree[dependant] -= 1
                if indegree[dependant] == 0:
                    ready.append(dependant)
                    ready.sort(key=self._sort_key)

        if len(ordered) != len(closure):
            raise ValueError("fixture dependency graph contains a cycle")
        return ordered

    def _find_cycle(self) -> list[str] | None:
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(fixture_id: str) -> list[str] | None:
            state[fixture_id] = 1
            stack.append(fixture_id)
            fixture = self.fixtures[fixture_id]
            for dependency_id in fixture.dependency_ids:
                if dependency_id not in self.fixtures:
                    continue
                dependency_state = state.get(dependency_id, 0)
                if dependency_state == 0:
                    cycle = visit(dependency_id)
                    if cycle:
                        return cycle
                elif dependency_state == 1:
                    start = stack.index(dependency_id)
                    return stack[start:] + [dependency_id]
            stack.pop()
            state[fixture_id] = 2
            return None

        for fixture_id in sorted(self.fixtures):
            if state.get(fixture_id, 0) == 0:
                cycle = visit(fixture_id)
                if cycle:
                    return cycle
        return None

    def _sort_key(self, fixture_id: str) -> tuple[int, str]:
        fixture = self.fixtures[fixture_id]
        return fixture.order, fixture.fixture_id

    @staticmethod
    def _issue(
        code: str,
        fixture: FixtureDefinition,
        message: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            severity=Severity.ERROR,
            message=message,
            sheet="Fixtures",
            row=fixture.source_row,
            column="F",
            entity_id=fixture.fixture_id,
            field="dependency_ids",
            suggestion="修正依赖 ID、启用状态或阶段后重新导入",
        )
