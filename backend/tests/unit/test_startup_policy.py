from maestro_app.application.startup_policy import explicit_startup_flows


def test_nested_startup_and_circular_references_are_bounded(tmp_path):
    contents = {
        "A": 'appId: example.app\n---\n- runFlow: {file: B.yaml, env: {ROLE: test}}\n- runFlow: missing.yaml\n',
        "B": 'appId: example.app\n---\n- runFlow: A.yaml\n- launchApp: {clearState: false}\n',
        "C": 'appId: example.app\n---\nnot-a-list\n',
        "D": 'appId: example.app\n---\n- runFlow: 123\n- runFlow: {}\n',
    }
    paths = {}
    for key, content in contents.items():
        path = tmp_path / f"{key}.yaml"
        path.write_text(content)
        paths[key] = path
    assert explicit_startup_flows(["A", "C", "D", "B"], paths) == ["B"]
