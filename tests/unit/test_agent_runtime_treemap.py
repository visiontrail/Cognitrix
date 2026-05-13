from apps.api.agent_runtime import _echarts_treemap_option


def test_echarts_treemap_option_builds_rich_hierarchy() -> None:
    option = _echarts_treemap_option(
        rows=[
            {"department": "Engineering", "employee": "Ada", "cost": 120, "level": "L5"},
            {"department": "Engineering", "employee": "Grace", "cost": 80, "level": "L4"},
            {"department": "Sales", "employee": "Lin", "cost": 50, "level": "L3"},
        ],
        x_key="department",
        y_key="cost",
        name_key="employee",
        title="Cost by department",
    )

    assert option["__cognitrixRichTreemap"] is True
    assert option["title"]["text"] == "Cost by department"

    series = option["series"][0]
    assert series["type"] == "treemap"
    assert series["__cognitrixRichTreemap"] is True
    assert series["visualDimension"] == 0
    assert series["nodeClick"] == "zoomToNode"
    assert series["label"]["rich"]["metric"]["fontWeight"] == 700
    assert len(series["levels"]) == 3

    engineering = series["data"][0]
    assert engineering["name"] == "Engineering"
    assert engineering["value"] == [200.0, 80.0, 2]
    assert engineering["itemCount"] == 2

    ada = engineering["children"][0]
    assert ada["name"] == "Ada"
    assert ada["value"] == [120.0, 48.0, 1]
    assert ada["shareOfParent"] == 60.0
    assert ada["rawFields"] == [{"name": "level", "value": "L5"}]


def test_echarts_treemap_option_keeps_flat_rows_when_no_leaf_label() -> None:
    option = _echarts_treemap_option(
        rows=[
            {"region": "North", "revenue": "20"},
            {"region": "South", "revenue": 30},
        ],
        x_key="region",
        y_key="revenue",
        name_key=None,
        title="Revenue",
    )

    series = option["series"][0]
    assert [node["name"] for node in series["data"]] == ["South", "North"]
    assert series["data"][0]["metricValue"] == 30.0
    assert series["data"][0]["shareOfTotal"] == 60.0
